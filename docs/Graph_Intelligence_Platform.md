```mermaid
flowchart TB

A[Insurance Data Sources]

B[Feature Engineering]

C[Feature Store]

D[Risk Models]

E[Fraud Models]

F[Entity Resolution]

G[Graph Database]

H[Graph Analytics]

I[Vector Search]

J[LLM Copilot]

K[Decision Support]

A --> B
B --> C

C --> D
C --> E

A --> F

F --> G
G --> H

A --> I

D --> K
E --> K
H --> K
I --> K

K --> J
```
