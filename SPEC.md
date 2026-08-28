# Build Prompt: M&S Credit Card Payment Calculator

## Role

You are guiding me through building and deploying a small self-hosted web application. Walk me through it step by step, produce complete runnable code, and explain the reasoning where a design decision matters. Ask me questions where this spec is ambiguous rather than guessing.

I'm technically comfortable — I run Proxmox VE, OPNsense, Tailscale and Home Assistant — so skip the basics, but do explain choices specific to this build.

## What I'm building

A payment calculator and ledger for a single M&S Bank credit card currently inside a 0% interest-free purchase promotion. Its job is to answer two questions each month:

1. **What is the bare minimum I must pay** to stay compliant with the card's terms and keep the 0% promotional rate intact?
2. **What should I pay** to clear the outstanding balance before the interest-free period ends?

The gap between those two numbers is the decision I'm making each month, so both must be displayed clearly and side by side, along with the shortfall between them.

## Card parameters

- The interest-free promotional period is **26 months** from the card's start date. (This comes from my offer letter, not the T&Cs — make the length and start date configurable rather than hard-coded.)
- The 0% rate holds **only if the minimum payment is made on time every month**. The T&Cs are explicit that a late minimum payment in any month forfeits the promotional rate — this is the single most important thing the app exists to prevent.
- The promotional window is a **single fixed window for the whole card**, not per-purchase. A purchase made in month 3 has 23 months left to clear; one made in month 18 has 8.
- One card only. No need to model multiple cards or multiple promotional windows.

## The minimum payment rules (from the M&S Bank / HSBC UK T&Cs)

The agreement is post-23 March 2011, so the contractual minimum payment is **the highest of these three**:

- **Option A:** interest added since the last statement, **plus** any default charges, **plus** 1% of the remainder of the amount owed
- **Option B:** 2.5% of the full amount owed
- **Option C:** £5

Plus this override: **if the total owed is under £5, the minimum payment is the full balance.**

### Important consequence to build around

While the 0% promotion is running and no default charges have landed, interest is zero, so Option A collapses to just 1% of the balance. That means **Option B (2.5%) will normally govern** the minimum payment, until the balance falls low enough that the £5 floor takes over.

But Option A can overtake Option B if a **default charge** hits. The T&Cs list £12 charges for a late minimum payment, for going over the credit limit, and for a returned payment. So implement all three options properly and take the maximum — don't shortcut to "2.5% or £5". Let me record default charges as ledger entries so the calculation reacts correctly when one occurs.

### Other relevant terms to encode or surface

- **Payment due date** is normally **25 days after the statement date**. Make the statement day of month configurable and derive the due date from it. Show me clearly how many days I have left before the next due date — this is the thing that protects the 0% rate.
- **Payment allocation order** when paying less than the full balance: arrears first, then the current month's minimum payment, then instalment plan amounts and fees, then the rest of the statemented transaction balance, then unstatemented transactions, then remaining instalment plan balances. Within each, highest interest rate first, and oldest first where rates match.
- **Non-sterling transactions** carry a 2.99% charge on top of the sterling amount. Give me an optional flag when entering a purchase so the app adds this automatically.
- **Instalment plans** are a separate mechanism in these T&Cs and are excluded from the transaction balance. **Treat them as out of scope** — but note in the code where they'd slot in, in case I take one out later.

Isolate all of this in a **single well-commented calculation module** with the percentages, the £5 floor, the £12 default charge and the 26-month term in a config file, so a rate change means editing one file.

## Core functionality

### Data entry (manual only)

Everything is entered by hand. **No bank integrations, no scraping, no automation, no agentic behaviour.** This is a straightforward calculator with a ledger behind it.

- **Purchases:** description, amount, date, optional non-sterling flag
- **Payments:** amount, date paid
- **Charges:** type (late payment / over limit / returned payment), amount, date — so the minimum payment calculation reflects reality
- **Card setup, entered once:** promotional start date, promotional length in months, statement day of month, credit limit

### Calculations

Compute and display:

- **Outstanding balance** — purchases plus charges minus payments
- **Months elapsed** and **months remaining** in the promotional window
- **Days until the next payment due date**
- **Contractual minimum payment** — the highest of Options A, B and C above, with the sub-£5 override. Show me **which option won and why**, because that's the bit I'd otherwise have to trust blindly.
- **Payoff payment** — outstanding balance divided by months remaining: the level monthly payment that clears the balance before the promotion ends
- **Shortfall** — the difference between the two, i.e. how far behind I fall by paying only the minimum
- **Projected end-of-promotion balance** if I only ever pay the contractual minimum. Paying 2.5% a month leaves a substantial balance at month 26 which then starts attracting the standard rate, and I want to see that number.
- **Credit limit headroom**, since going over triggers a £12 charge which then inflates the minimum

Handle these edge cases and tell me how you've handled them:

- a purchase made late in the term, compressing the payoff figure
- months remaining hitting zero or going negative
- a zero or negative balance
- a payment exceeding the outstanding balance (the T&Cs say overpayments get refunded rather than held as credit)
- the balance falling below £5

### Interface

- Web interface, usable from a laptop or a phone browser
- Summary panel at the top: outstanding balance, months remaining, days until due, contractual minimum, payoff payment, shortfall
- Forms to add a purchase, a payment and a charge
- Chronological ledger with a running balance, with edit and delete — I will mistype an amount at some point
- A month-by-month projection table comparing minimum-only against the payoff schedule
- Readable on a phone. No application-level login needed, given the network access model below.

## Technical requirements

- **Storage:** SQLite. Trivial data volume, and I want a single portable file I can back up.
- **Money handling:** integer pence or Decimal throughout, never floats. Be explicit about rounding — round the minimum payment up to the penny so I never underpay by a rounding error and lose the 0% rate.
- **Stack:** Python with a lightweight web framework is my preference. If you'd suggest otherwise, make the case before writing code.
- **Deployment on Proxmox VE:** I'd like this as its own **LXC container** — recommend privileged vs unprivileged and justify it. Give me the container creation steps, a Debian template choice, the systemd unit to run the app, and a bind mount or dedicated dataset for the SQLite file so it survives rebuilds. If you think Docker inside the LXC is the better route, argue for it rather than assuming.
- **Access:** reachable over **Tailscale only** — already running on my network. It must not be exposed to the internet or reachable from the wider LAN. Cover what Tailscale in an LXC needs (TUN device access on unprivileged containers), whether to run Tailscale in the container or use a subnet router, and how to bind the app so it only listens on the tailnet interface. Then tell me how to **verify** that, not just assume it.
- **Backups:** a simple approach for the SQLite file, ideally hooking into Proxmox's own backup of the container.

## What I want from you

1. Confirm your understanding and flag anything underspecified or that you'd do differently.
2. Propose the file structure before writing code.
3. Produce the code file by file, complete and runnable — not fragments.
4. Give me the Proxmox deployment steps, including verifying Tailscale-only access.
5. Write tests for the minimum payment calculation specifically, covering each of the three options winning, the sub-£5 case, and a default charge flipping the result from Option B to Option A.
