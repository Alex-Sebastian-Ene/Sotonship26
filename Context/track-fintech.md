---
doc: track-brief
track: FinTech
event: SotonShip 2026
partners: [JPMorganChase, Deutsche Bank, TrueMoney]
source: Raw/fintech-brief.pdf (5 pages, generated 2026-10-15)
see_also: event-rules.md
---

# FinTech track

## Challenge
Build an **AI-powered product** that solves a real problem for someone who **saves, spends, sends or manages money**, and that you could put in front of them after the weekend. You choose the problem.

**Context:** Banks, fintechs and wallet providers spend heavily on fraud, compliance and payments operations. Small businesses, migrant workers and vulnerable customers are still poorly served.

**Pitch sentence:**
> We help [a specific person] to [do or decide something] in [part of finance] using [AI and the data behind it].

*Example:* We help remittance users stop scam payments before they leave by spotting the warning signs in the messages that prompted them.

## Who to build for
Pick **one main user**. One customer type, team or payment type done well beats covering all of finance.

- **Customers:** migrant worker sending money home, student, older person, someone recovering from a scam
- **Bank or fintech staff:** fraud, payments operations, compliance/KYC, trade finance, customer services
- **Small business or sole trader**
- **Wallet agent or kiosk operator**

## In scope
Scams and fraud · money laundering · cross-border payments and remittance · payment data · trade and business verification · small-business cash flow · regulation and compliance · digital money.

## Out of scope
- A general finance chatbot, or a trading bot or price prediction that doesn't lead to a decision
- An existing product with an AI feature added on top
- Anything needing **real customer data, live bank credentials or moving real money**, unless an organiser agreed it in advance

## Must show
1. **A real financial problem:** who has it, how often, what they do today. Back it with evidence (published data, a regulation, a conversation).
2. **AI the product depends on:** if the product still does its main job without the AI, rethink it. Where the AI classifies, predicts or extracts, beat a simple baseline.
3. **Works on real data:** the main task runs end to end, live, on **public or openly licensed data** with the source and date visible. Synthetic data is OK for testing and for anything personal, if labelled.
4. **Business case:** who pays (bank, fintech, wallet provider, businesses, customers), rough cost per user including AI, and what it takes to work for a **second bank or second market**.
5. **Honesty about limits:** what it doesn't know, data age, and behaviour when data is missing or stale or the input is out of scope. **Demo at least one failure.**

## Example directions (optional)

### 1. Scam check for people sending money home
- **Problem:** Migrant workers sending money abroad are prime scam targets, including deepfake "relative in distress" calls. **UK reimbursement rules don't cover international payments.**
- **Product:** Reads the message or call behind a transfer, spots the warning signs and warns the sender before the money leaves.
- **Buyer:** A wallet or remittance provider. Each prevented scam saves a refund, a complaint and a lost user.
- **Baseline:** A keyword list.
- **Data:** Published scam scripts, public scam reports.

### 2. Shell-company check for business onboarding
- **Problem:** Fraudsters open business accounts through shell companies with fake directors and mass-registration addresses.
- **Product:** Takes a new business customer's details, pulls their Companies House record and director network, and explains the risk signals found. Saves onboarding teams hours per case.
- **Buyer:** Banks and fintechs that open business accounts. Every UK lender runs the same checks, so there are many potential buyers.
- **Data:** The free Companies House API and bulk data are enough.

### 3. Payment address fixer
- **Problem:** Swift is moving cross-border payments to **structured addresses** (street, town, country…) and will stop accepting free-text addresses once timing is agreed with the industry. Many banks hold messy free-text addresses.
- **Product:** Cleans and structures addresses, flags the uncertain ones and explains why. Prevents rejected payments and manual repairs.
- **Buyer:** Transaction banks. The rule applies to every bank on Swift worldwide.
- **Baseline:** Simple pattern-matching rules.
- **Data:** Open address data, e.g. OpenStreetMap.

### 4. Trade document checker
- **Problem:** Before paying out under a **letter of credit**, staff check by hand that the invoice, bill of lading and other documents match each other and the credit's terms.
- **Product:** Reads the documents, extracts key fields and lists every discrepancy. Also catches forged or reused documents.
- **Buyer:** Banks with trade finance businesses, licensed per document checked.
- **Data:** Public sample trade documents, plus generated sets with planted errors.

## Data sources
None compulsory. Any permitted source is fine if credited. Check market coverage and usage rights early.

| Source | What it offers | Access and limits |
|---|---|---|
| [Companies House API and bulk data](https://developer.company-information.service.gov.uk/) | UK company records, officers, registered addresses, filing history, persons with significant control | Free; API needs a key. Bulk files are large, so take a slice |
| [UK sanctions list (OFSI / FCDO)](https://www.gov.uk/government/publications/the-uk-sanctions-list) | Names, aliases, identifiers of sanctioned people and entities | Free public download; good for name-matching and screening |
| [World Bank Remittance Prices Worldwide](https://remittanceprices.worldbank.org/) | Cost of sending money between country pairs, by provider type | Free download; quarterly, not live prices |
| [Bank of England](https://www.bankofengland.co.uk/boeapps/database) and [ECB](https://data.ecb.europa.eu/) exchange rates | Daily reference FX rates | Free; historical reference rates, not live trading rates |
| [FCA Register](https://register.fca.org.uk/) and FCA / BoE publications | Authorised firms, warnings about unauthorised firms, policy statements, consultations | Public pages and downloads; check terms before bulk collection |
| [PaySim (Kaggle)](https://www.kaggle.com/datasets/ealaxi/paysim1) | Synthetic mobile-money transactions with fraud labels | Open; widely used, so originality must come from your product |
| [IBM AMLworld (Kaggle)](https://www.kaggle.com/datasets/ealtman2019/ibm-transactions-for-anti-money-laundering-aml) | Synthetic transactions with labelled money-laundering patterns | Open; large, so sample it |
| [Elliptic dataset (Kaggle)](https://www.kaggle.com/datasets/ellipticco/elliptic-data-set) | Bitcoin transaction graph with licit/illicit labels | Open; check the licence |
| Public blockchain explorers ([Etherscan](https://etherscan.io/), [Basescan](https://basescan.org/)) | On-chain token transfers, incl. stablecoins and deposit tokens | Free tiers need a key; rate limited |
| [OpenStreetMap](https://www.openstreetmap.org/) | Structured address data | Open (ODbL); credit OpenStreetMap contributors |

## Track-specific rules (in addition to event-rules.md)
- **No real customer data.** Don't connect to a real bank account, card or wallet. **Never move real money.**
- Build tools that **detect** scams and fraud, not tools that **create** deepfakes, scam scripts or fake documents.
- For investment, credit or borrowing, **link to official guidance** (FCA, MoneyHelper) rather than giving your own advice.

## Pitch must clearly answer
1. What **evidence** shows the problem is real and costly?
2. Who would **deploy and pay** for it?
3. What would it take to roll it out to a **second bank or market**?
