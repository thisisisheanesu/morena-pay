"""MORENA Pay: a Nigerian fintech assistant that runs on a CPU.

    modal deploy serve.py

Its own app and its own URL. Pay and Studio were one deployment serving two pages and two models,
which made them look like one product with a second tab. They are not: Pay is a payments assistant
that has to know when NOT to act, Studio turns a spoken brief into a video instruction. They want
different models, they fail in different ways, and they should be able to move independently.

Pay runs nano. On the held-out Paystack menu nano and mini tie on tool choice, but nano abstains on
requests that need no tool 100% of the time against mini's 37.5%. Pay is the page people prod with
small talk, and a balance lookup in reply to "good morning" is the most visible failure it has.
"""
import os

import modal

APP = "morena-pay"
GGUF = os.environ.get("MORENA_PAY_GGUF", "nano-tools-Q4_K_M.gguf")
MODEL_DIR = "/models"
HERE = os.path.dirname(os.path.abspath(__file__))

image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("build-essential", "cmake")
    .pip_install("llama-cpp-python==0.3.16", "fastapi[standard]==0.115.6")
    .add_local_dir(os.path.join(HERE, "app"), "/ui")
)
vol = modal.Volume.from_name("morena-pay-models", create_if_missing=True)
app = modal.App(APP)


@app.cls(image=image, volumes={MODEL_DIR: vol},
         cpu=4, memory=4096, scaledown_window=300, timeout=600, max_containers=4)
@modal.concurrent(max_inputs=4)
class Pay:
    @modal.enter()
    def load(self):
        self.error = None
        self.llm = None
        vol.reload()

    def _model(self):
        """Load the model only if something actually asks the server to run it.

        The page runs the model itself, in the browser, and only falls back to here when the
        browser cannot. Loading it up front cost 43 seconds of cold start on every request,
        including the request for the HTML and the weights, so the page sat waiting on a server
        it was about to stop needing.
        """
        if self.llm is not None or self.error:
            return self.llm
        from llama_cpp import Llama
        try:
            path = os.path.join(MODEL_DIR, GGUF)
            if not (os.path.exists(path) and os.path.getsize(path) > 10_000_000):
                raise FileNotFoundError(
                    f"{path} missing. Push it with: modal volume put morena-pay-models {GGUF}")
            # n_threads matches the 4 cores requested; llama.cpp otherwise guesses from the host,
            # which on a shared machine means oversubscribing and getting slower.
            self.llm = Llama(model_path=path, n_ctx=4096, n_threads=4, n_batch=512, verbose=False)
        except Exception as e:
            self.error = f"{type(e).__name__}: {e}"
        return self.llm

    @modal.asgi_app()
    def web(self):
        from fastapi import FastAPI, Request
        from fastapi.responses import FileResponse, JSONResponse

        api = FastAPI(title="MORENA Pay")

        # Cross-origin isolation, so the browser will hand out SharedArrayBuffer and wllama can
        # run llama.cpp on more than one thread. "credentialless" rather than "require-corp"
        # because the wasm binary comes from a CDN that does not send CORP headers.
        # no-store on the page itself. Without a Cache-Control header a browser falls back to
        # heuristic caching, 10% of the document's age, and FileResponse sends
        # last-modified: Thu, 01 Jan 1970, which makes that age half a century. The page was
        # being cached for years: deploys went out and nobody saw them. The weights keep their
        # immutable year, because those really never change under a given name.
        ISOLATE = {"Cross-Origin-Opener-Policy": "same-origin",
                   "Cross-Origin-Embedder-Policy": "credentialless",
                   "Cache-Control": "no-store, must-revalidate"}

        @api.get("/")
        def index():
            return FileResponse("/ui/index.html", headers=ISOLATE)

        # GET and HEAD both: wllama asks for the size and etag with a HEAD before it starts
        # downloading, and FastAPI answers a GET-only route with 405, which strands the loader.
        @api.api_route("/model.gguf", methods=["GET", "HEAD"])
        def model_gguf():
            """The weights themselves, so the page can run the model instead of asking us to.

            This is the whole point of the demo: a model small enough that the device it is
            being shown on can run it. Serving it is cheaper than serving inference, and it is
            fetched once and then lives in the browser's cache."""
            path = os.path.join(MODEL_DIR, GGUF)
            if not os.path.exists(path):
                return JSONResponse({"error": f"{GGUF} not on the volume"}, status_code=404)
            return FileResponse(path, media_type="application/octet-stream",
                                headers={"Cache-Control": "public, max-age=31536000, immutable",
                                         "Access-Control-Allow-Origin": "*"})

        @api.get("/console.html")
        def console():
            return FileResponse("/ui/console.html", headers=ISOLATE)

        @api.get("/props")
        def props():
            # Answers from the filename on the volume, without loading anything.
            return {"model_path": GGUF, "n_ctx": 4096, "gguf_url": "/model.gguf"}

        @api.post("/completion")
        async def completion(req: Request):
            llm = self._model()
            if llm is None:
                return JSONResponse({"error": self.error}, status_code=503)
            b = await req.json()
            prompt = b.get("prompt") or ""
            if not prompt:
                return JSONResponse({"error": "no prompt"}, status_code=400)
            # A public URL is an open text box, so the ceilings sit where the demo lives rather
            # than where the model could go.
            n = min(int(b.get("n_predict") or 200), 320)
            out = llm(
                prompt[-14000:],
                max_tokens=n,
                temperature=float(b.get("temperature") or 0.0),
                top_p=float(b.get("top_p") or 1.0),
                stop=b.get("stop") or ["<reserved_0>", "<reserved_5>", "<|tool_result|>"],
                echo=False,
            )
            return {"content": out["choices"][0]["text"]}

        return api
