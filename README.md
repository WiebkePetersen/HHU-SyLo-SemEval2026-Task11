This Repo contains our Submission for **Semeval 2026 Task 11 : Disentangling Content and Formal Reasoning in Large Language Models.**

**Lets use our Hybrid to navigate through this Syllogistic World!** 🧭🚙 

🚖 Our Approach :
Our system focuses on **reasoning disentanglement**separating strict syllogistic validity from semantic plausibility. 

To achieve this, we compare **direct neural inference** against two **hybrid neuro-symbolic pipelines**:
1. Translation to **first-order logic (FOL)**
2. Translation to **syllogistic triples**

By offloading the inference step to symbolic theorem provers, these hybrid models effectively mitigate content bias and significantly improve logical fidelity.


🗂️ What's in this Repository:

📄 `experiments.yaml`: The most important file in the repo. Here you can find the detailed configurations and descriptions for all the experiments we ran.

📁📄 `prompts/examples.json`: Contains the specific few-shot examples we used for our experiments.

📁 `prompts/` (folder): Includes all the base prompt templates utilized across our different model pipelines.
