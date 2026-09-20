# Architecture and flow

Open [architecture.excalidraw](architecture.excalidraw) in Excalidraw using **Open** to edit the architecture and flow diagram. It depicts the proposed design, not implemented software.

```mermaid
flowchart TD
    S[Approved subject + frozen sources + run manifest] --> G[Generate shared immutable MCQ pool]
    G --> V[Deterministic validation]
    V -->|valid: same inputs and context| A[A: Generative rubric filter]
    V -->|valid: same inputs and context| B[B: JEV atomic rubric filter]
    V -->|invalid| W[Withheld / unresolved records]
    A --> PA[Quality policy A]
    B --> PB[Quality policy B]
    PA -->|pass| DA[Diversity + coverage selection A]
    PB -->|pass| DB[Diversity + coverage selection B]
    PA -->|fail / uncertain / error| W
    PB -->|fail / uncertain / error| W
    DA --> QA[Selected originals A]
    DB --> QB[Selected originals B]
    DA -->|redundant / excess coverage| X[Selection exclusions with evidence]
    DB -->|redundant / excess coverage| X
    QA --> H[Downstream final human approval]
    QB --> H
    G -.-> U[Blinded audit of immutable inputs]
    U --> R[Paired quality / cost / time / diversity report]
    QA --> R
    QB --> R
    W --> R
    X --> R
```

All stages commit events and state to SQLite. The durable journal and immutable artifacts feed reports and a shared live/replay projection, which later drives a TUI. The audit is an experiment measurement: it includes filtered-out inputs, not just the approval queue. Humans are not expected to revise rejected questions. Only an explicit downstream human decision can approve an MCQ for use.

```mermaid
flowchart LR
    CLI[CLI coordinator + local provider adapters] --> DB[(SQLite state + append-only events)]
    CLI --> ART[Immutable input / source / result artifacts]
    DB --> E[JSONL event export]
    DB --> P[Versioned projection / reducer]
    E --> P
    ART --> P
    P --> R[Text / JSON benchmark report]
    P --> T[Future live TUI + animated replay]
```
