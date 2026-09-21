# MORENA Pay

A Nigerian fintech assistant that turns Pidgin, Yoruba, Igbo, Hausa and English into real API
calls, running on a laptop CPU. 209M parameters, no GPU, no network.

Live: **https://vambo--morena-pay-pay-web.modal.run**

```
"Abeg send 5000 naira give Chidi."
  -> transfer_initiate {amount: 5000, recipient: "Chidi", currency: "NGN"}

"Nawa nake da shi?"                       (Hausa, four words)
  -> balance_fetch {}

"Thank you o, you don try well well."
  -> answers in Pidgin, calls nothing
```

The model is [MORENA](https://huggingface.co/collections/vamboai/morena) 0.2B fine-tuned for tool
calling. Training pipeline and data: [morena-tools](https://github.com/thisisisheanesu/morena-tools).
The video demo is a separate product: [morena-studio](https://github.com/thisisisheanesu/morena-studio).

## What it does that is hard

The ten tools come from the real Paystack OpenAPI spec and appear nowhere in the training data.
The names are not guessable: `transferrecipient_create`, `bank_resolveAccountNumber`. Getting one
right means reading a schema rather than recognising a name.

| | base | this |
|---|---|---|
| Picks the right tool | 9% | **90.9%** |
| Decides to call without being told to | 27.3% | **90.9%** |
| Uses only the arguments the tool declares | 0% | **100%** |
| Changes one field without touching the rest | 0% | **100%** |
| Stays quiet when no tool fits | 12.5% | **100%** |
| Follows a mid-conversation language switch | 0% | **100%** |
| Carries a thread across six turns | 0% | **100%** |

The third and fourth rows are the ones worth caring about. Asked to change an amount, most small
models re-emit the whole call from memory and quietly corrupt a field nobody mentioned. This one
returns `{"op":"patch","set":{"amount":2500}}` and leaves everything else alone.

## The app

A single HTML file. A phone-shaped bank app on desktop, the app itself on mobile with no mockup
around it. Type in any of the languages, a confirm sheet slides up with the fields filled, correct
one detail in words and only that field changes, confirm and the balance moves.

Beside it, a panel explaining in plain words what the model just did, including when it gets it
wrong. It reports a clarifying question as a question rather than as a success, because this model
sometimes asks before acting and a demo that only congratulates itself is an advert.

## Running it

```bash
modal deploy serve.py                       # needs the weights on the volume
modal volume put morena-pay-models nano-tools-Q4_K_M.gguf
```

Locally against any llama.cpp server:

```bash
llama-server -m nano-tools-Q4_K_M.gguf --path app --no-jinja -c 4096
```

`--no-jinja` matters: the app drives the raw completion endpoint, and the chat-template parser
rejects an otherwise valid response when the model trails a stray byte.

Do not set a repetition penalty. It penalises repeated braces and quotes, which is what JSON is
made of, and pushes the model into an invalid token right after a correct call.

## Licence

Apache 2.0. Independent demo, not affiliated with or endorsed by Paystack.
