# Asta Scholar QA

SQA is the long-form question answering system published in Singh et al., 2025.
It has a retrieval and reranking component and a multi-step LLM to create the final report.

SQA is intended to be run only against the `sqa_dev` or `sqa_test` tasks.


This also requires a reranker model, [mxbai-rerank-large-v1](https://huggingface.co/mixedbread-ai/mxbai-rerank-large-v1) to select the top 50 search results.
The reranker can be deployed on a service like Modal, in which case the [`MODAL_TOKEN`](https://modal.com/) to be set as an environment variable, 
and the <app_name> and <api_name> params have to be passed as params to the script as below (with an optional batch size param):

```bash
./solvers/sqa/demo.sh -S reranker_type=modal -S app_name=<app_name> -S api_name=<api_name> -S batch_size=256
```

Alternatively, the reranker can be run locally as an instance of SentenceTransformer as below:

```bash
./solvers/sqa/demo.sh -S reranker_type=crossencoder -S model_name_or_path=mixedbread-ai/mxbai-rerank-large-v1
```
*Please ensure you have torch and transformers installed in your environment for local reranking.*