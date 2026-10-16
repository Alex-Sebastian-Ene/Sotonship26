---
doc: track-brief
track: Responsible AI
event: SotonShip 2026
partners: [RAi UK]
source: Raw/responsible-ai-brief.pdf (6 pages, generated 2026-10-15; sources checked 2026-10-15)
see_also: event-rules.md
---

# Responsible AI track

## Challenge
Build a product that makes **AI useful and trustworthy for a specific person**, and pitch it as a **business**. It can be either:
- a tool that helps others **develop, test or govern AI**, or
- an AI-powered product in **any sector** where responsible design is central to the value it delivers.

You choose the problem, sector and technology. Deliver a working product with **evidence of benefit, a clear buyer and a credible way to grow**. A focused product one customer could trial beats a broad promise to make all AI safe. **Responsibility must change what the product does, how it is tested, or what its users can control.**

**Pitch sentence:**
> We help [a specific person] to [do or decide something] using [AI or an AI assurance tool], **while reducing [a specific risk to people]**.

*Example:* We help customer-support teams test whether their AI answers are supported by approved sources before a chatbot update reaches customers.

## Who to build for
Choose **one main user and one potential buyer**. They may be different people.
- **Users:** developer, service worker, teacher, AI procurement team, small business, someone affected by an AI decision
- Design around **one workflow**. Identify who **benefits**, who could be **harmed** and who can **put mistakes right**.

## In scope
Any sector. Possible themes: fairness · privacy · security · reliability · transparency · accessibility · human oversight · participation · environmental impact. You don't need every theme: pick the risks that matter for your user and **make the improvement testable**.

Responsible AI must be **central to both the problem and the product**.

## Out of scope
- A generic chatbot, ethics checklist or dashboard with no specific user, decision or action
- Claims that a system is "fair", "safe" or "compliant" without a defined scope and supporting evidence
- An earlier project resubmitted as new work, or a demo that depends on restricted systems or real sensitive personal data

## Must show
1. **A real problem and the people affected:** who, how often, what they do today. Back it with research, published evidence or a conversation. Name a **concrete** benefit or harm, not a general concern about AI.
2. **AI at the core:** show the AI capability the product uses or improves. An **assurance tool qualifies** by testing or governing a running AI system; it doesn't need an LLM added to its checker. Compare the important step to a simple baseline (rules, manual review, or the same model **without your safeguard**).
3. **A product that works:** a user completes the main task end to end. Use public or openly licensed material and **reproducible test cases**, with sources and dates visible. Label synthetic inputs. **Keep test cases separate from tuning examples. Report sample sizes as well as results.**
4. **A business case:** the user, the paying customer or funder, the cost of the problem, a price or funding model, and a route to a **first pilot**. Estimate **AI, hosting and human-review costs per use**. Explain why a buyer would choose you over existing tools and what changes for a **second customer**.
5. **Evidence of responsibility and honest limits:**
   - one **measurable improvement and its trade-off** (e.g. fewer unsupported answers at the cost of more handoffs)
   - **demonstrate one failure** and what happens next
   - state **who can review, override or challenge** the output
   - state what evidence is still needed before real deployment

## Example directions (optional)
The papers back the methods. The products, buyers and business models are **unvalidated proposals**.

### 1. Release check for customer-support AI
- **Basis:** RAGAs [2], which evaluates retrieval-augmented answers, including faithfulness to retrieved material.
- **Product:** Runs test questions against a support chatbot, highlights unsupported claims and creates a review queue.
- **Buyer:** A software company or support agency, paying per bot or per test run.
- **Data:** Licensed public help pages, with deliberately answerable **and** unanswerable questions.
- **Evaluation:** Compare against the same bot without the check. Measure missed errors and false alarms against human-labelled answers.
- **Caveat:** Automated evaluation is evidence for a reviewer, not proof that every answer is true.

### 2. Fairness check before an AI update
- **Basis:** Gender Shades [3] found large error-rate differences across gender and skin-type groups in three commercial classifiers. That motivates checking per group rather than relying on one average. It does **not** show the same disparities exist in every domain.
- **Product:** A release-review tool for one classifier (e.g. routing customer requests).
- **Buyer:** A product team, paying a subscription that covers its models.
- **Data:** Labelled synthetic cases or a suitably licensed benchmark. Compare versions and show **subgroup error rates, sample sizes and trade-offs**.
- **Constraints:** **Don't infer sensitive traits from names or faces.** Synthetic results demonstrate the workflow, not fairness in a real population.

### 3. Evidence assistant for buying AI
- **Basis:** Model Cards [4] and Datasheets for Datasets [5], which propose structured documentation of intended uses, evaluations and data provenance.
- **Product:** Compares a buyer's needs with supplier documentation, quotes supporting passages and flags missing evidence for a person to review.
- **Buyer:** A small company, procurement team or consultancy, paying per supplier assessment.
- **Data:** Public model cards, plus clearly labelled **fictional** supplier packs with planted omissions.
- **Evaluation:** Compare against a manual checklist. Measure missed gaps, invented claims and review time.
- **Caveat:** Sell faster evidence review, **not** automatic certification or legal approval.

### 4. Service tool that knows when to hand over
- **Basis:** SelectiveNet [6], which studies prediction with a **reject option** and the error vs. coverage trade-off.
- **Product:** An AI tool routes maintenance requests when evidence is sufficient and sends uncertain cases to a worker.
- **Buyer:** A facilities provider, paying per site or per request.
- **Data:** Synthetic requests with known categories, including ambiguous and unfamiliar examples.
- **Evaluation:** Compare with routing every request automatically. Report errors, the fraction handled automatically and the human queue.
- **Caveat:** This is an adaptation to test, not a claim the paper validates your workflow. **Show what happens when the reviewer is unavailable.**

## Data and tools
None compulsory. Check reuse rights before building.

| Source | What it offers | Access and limits |
|---|---|---|
| [Ragas repository](https://github.com/vibrantlabsai/ragas) | Evaluation tools for LLM applications; linked to the RAGAs paper [2] | Apache-2.0 code. Model/API use may cost money; validate automated scores with human checks |
| [Fairlearn](https://fairlearn.org/main/about/index.html) | Metrics and methods for assessing model performance across groups | MIT code. Dataset licences are separate; no single metric guarantees fairness |
| [Hugging Face model cards](https://huggingface.co/docs/hub/model-cards) | Public documentation of intended use, evaluation, limitations | Check each repo's terms. Public access alone doesn't grant reuse rights |
| Public manuals and help pages | Source material for grounded answers and evidence-review tasks | Choose content with permission to reuse; record owner, version, URL, date |
| Labelled synthetic test cases | Fictional records, planted errors, ambiguous inputs, controlled group comparisons | State how cases and labels were made. Keep a held-out test set; don't claim population-level validity |

The README must also record **model and tool versions, data licences, how the test set was built and the limits of your evidence**.

## Track-specific rules (in addition to event-rules.md)
- Credit research, code, models and data, **with dates and licences**. Disclose AI-generated work, prior components and outside help in the README.
- Label cached and synthetic data. **Show uncertainty.** Avoid safety, fairness or compliance claims beyond what your tests support.
- No private customer records or sensitive personal data in the demo. **Don't send confidential information to external AI services.** Only test systems you own or are authorised to test.
- **Use a sandbox:** no real consequential decisions about people. For health, safety, legal or financial uses, show **qualified human review** and link to official guidance.

## Judging note
The weights are the same as in the other tracks (see event-rules.md), but **Responsible AI shapes the evidence across all five criteria**, not just "Responsibility and trust".

## Pitch must clearly answer
1. What **problem and AI-related risk** have you evidenced?
2. Who would **adopt and pay**, and why?
3. What would it take to serve a **second customer responsibly**?

Also show: **the working core, one failure, the measured benefit and the cost of your safeguard.**

## References
Checked 15 Oct 2026.
1. RAi UK (track partner; responsible AI research across health, law enforcement, financial services). *Research overview.* https://rai.ac.uk/research-overview/
2. Es, S., James, J., Espinosa Anke, L. & Schockaert, S. (2024). *RAGAs: Automated Evaluation of Retrieval Augmented Generation.* EACL System Demonstrations, 150–158. https://aclanthology.org/2024.eacl-demo.16/
3. Buolamwini, J. & Gebru, T. (2018). *Gender Shades: Intersectional Accuracy Disparities in Commercial Gender Classification.* PMLR 81, 77–91. https://proceedings.mlr.press/v81/buolamwini18a.html
4. Mitchell, M. et al. (2019). *Model Cards for Model Reporting.* FAT*. https://arxiv.org/abs/1810.03993
5. Gebru, T. et al. (2021). *Datasheets for Datasets.* Communications of the ACM. https://arxiv.org/abs/1803.09010
6. Geifman, Y. & El-Yaniv, R. (2019). *SelectiveNet: A Deep Neural Network with an Integrated Reject Option.* PMLR 97, 2151–2159. https://proceedings.mlr.press/v97/geifman19a.html
