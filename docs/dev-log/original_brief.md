> Historical: the original project brief this repository was built from (a prompt written for an AI coding agent). Not maintained; the current state is described in README.md and docs/.

# AI F1 ENGINEERING AGENT — END-TO-END PROJECT BUILD

## 1. ROLE

You are the lead software architect, AI agent engineer, CAD automation engineer, and engineering workflow designer responsible for building this project.

You are working inside an existing project folder named:

`AI_F1_Engineering_Agent`

Your task is to build the project end-to-end as a real, modular, maintainable AI Engineering Agent.

Do not treat this as a simple CAD automation script.

The ultimate goal is to create an AI engineering agent that can receive an engineering design request, reason about the requirements, identify missing information, make explicit engineering assumptions, consider applicable FIA technical constraints, inspect existing vehicle/component information, create parametric CAD geometry in Autodesk Fusion 360 through the available Fusion MCP integration, validate the result, and eventually assemble independently created components into a complete F1 concept vehicle.

The F1 vehicle is the first major engineering problem used to develop and demonstrate the agent.

The actual product is the AI Engineering Agent.

---

# 2. PROJECT VISION

The final system should behave conceptually like an AI engineer.

A user should eventually be able to say something such as:

> "Design a front wing for our F1 concept vehicle according to the applicable 2026 FIA technical regulations."

The agent should NOT immediately start drawing.

It should follow an engineering workflow:

1. Understand the request.
2. Extract requirements.
3. Identify missing information.
4. Determine what existing vehicle/component information is relevant.
5. Identify applicable engineering and FIA constraints.
6. State assumptions explicitly.
7. Create an engineering design plan.
8. Generate a parametric CAD model.
9. Validate the geometry.
10. Check interfaces with existing components.
11. Perform basic manufacturability checks.
12. Detect problems.
13. Revise the design if necessary.
14. Save/register the resulting component.
15. Report what was created, what was verified, what was assumed, and what remains unverified.

The agent should behave as an engineering assistant/agent rather than as a conversational chatbot.

---

# 3. IMPORTANT SCOPE

The first version of the project must focus on these capabilities:

### Phase 1 — Requirements

* Requirement extraction
* Requirement clarification
* Missing-information detection

### Phase 2 — Engineering reasoning

* Explicit assumptions
* Design planning
* Constraint identification

### Phase 3 — CAD

* Fusion 360 integration
* Parametric CAD generation
* Meaningful feature/parameter naming
* Geometry inspection

### Phase 4 — Validation

* Basic geometric validation
* Interface validation
* Collision/interference checking where possible
* Basic manufacturability checking
* FIA constraint checking where structured rules are available

### Phase 5 — Vehicle structure

* Independent component management
* Component positions
* Component interfaces
* Vehicle coordinate system
* Assembly relationships

### Phase 6 — F1 concept vehicle

* Multiple independently created components
* Final Fusion assembly
* Consistent coordinate system
* Component relationships

Do NOT attempt advanced CFD, FEA, vehicle dynamics, thermal simulation, or full FIA homologation in the first implementation.

Those are future extensions.

The architecture must, however, be designed so that these capabilities can be added later.

---

# 4. WHAT THIS PROJECT IS NOT

Do NOT build:

* A simple prompt wrapper around Claude.
* A script that blindly creates CAD geometry.
* A static F1 model generator.
* A collection of unrelated Python scripts.
* A system that relies entirely on Claude's conversational memory.
* A system that claims official FIA compliance without verification.
* A system that invents regulatory requirements.

The architecture must separate:

* AI reasoning
* engineering data
* regulatory data
* deterministic calculations/checks
* CAD execution
* validation
* persistent project state

---

# 5. EXISTING TECHNOLOGY STACK

Assume the following environment is available:

* Claude / Claude Code
* Visual Studio Code
* Python
* Autodesk Fusion 360
* Autodesk Fusion MCP / Fusion MCP integration
* Git
* JSON/YAML as appropriate for structured project data

The Fusion MCP connection has already been successfully tested.

Claude has already demonstrated the ability to:

* create sketches in Fusion
* create parametric geometry
* create features
* create holes
* create fillets
* modify parameters
* inspect resulting geometry
* create a 3D model from a technical drawing/image
* recover from some Fusion modeling errors

Therefore, do not redesign or replace the existing Fusion MCP integration unless inspection proves it is necessary.

First inspect the existing environment and determine how the available Fusion MCP tools are exposed.

---

# 6. CORE ARCHITECTURE

Build the system around the following conceptual architecture:

USER
↓
AI ENGINEERING AGENT
↓
Requirement Analysis
↓
Missing Information Detection
↓
Engineering Assumptions
↓
Constraint / Rule Retrieval
↓
Vehicle / Component Context
↓
Engineering Design Plan
↓
Fusion CAD Execution
↓
Geometry Validation
↓
Interface Validation
↓
Manufacturability Validation
↓
Revision / Iteration
↓
Component Registration
↓
Assembly

The architecture should be modular.

At minimum, separate the following logical responsibilities:

### Agent / reasoning layer

Responsible for:

* interpreting user requests
* planning
* deciding what information is needed
* deciding which tools/data should be consulted
* coordinating the workflow

### Engineering data layer

Responsible for:

* vehicle state
* components
* interfaces
* parameters
* assumptions
* revisions

### Rule layer

Responsible for:

* FIA rules
* engineering rules
* rule applicability
* rule validation

### CAD layer

Responsible for:

* Fusion communication
* model creation
* model inspection
* parameter modification
* component management

### Validation layer

Responsible for:

* geometry checks
* interfaces
* collisions
* manufacturability
* regulatory checks

### Persistence layer

Responsible for:

* storing project state
* storing component information
* storing revisions
* storing validation results

---

# 7. FIRST PRINCIPLE: DO NOT TRUST AI MEMORY

The vehicle must have persistent engineering memory outside of the conversation.

The agent must be able to reconstruct the current state of the vehicle from project data.

The system should maintain information such as:

* vehicle identity
* coordinate system
* components
* component locations
* component revisions
* interfaces
* mounting points
* parameters
* applicable rules
* assumptions
* validation results
* Fusion references

Use a simple robust implementation initially.

Prefer JSON/YAML or SQLite depending on what is most appropriate after inspecting the project.

Do not introduce a complex database architecture unless necessary.

The first implementation should be easy to understand and modify.

---

# 8. VEHICLE COORDINATE SYSTEM

Establish a global vehicle coordinate system.

Use this convention unless there is a strong engineering reason to change it:

* +X = vehicle front
* -X = vehicle rear
* +Y = vehicle left
* -Y = vehicle right
* +Z = upward
* -Z = downward

All vehicle components must eventually be representable in this coordinate system.

The coordinate system must be documented clearly.

Do not allow individual components to use undocumented arbitrary coordinate systems.

---

# 9. COMPONENT MODEL

Every CAD component should eventually have a structured engineering record.

Conceptually:

```text
Component
├── ID
├── Name
├── Revision
├── Type
├── Status
├── Coordinate system
├── Position
├── Orientation
├── Parameters
├── Interfaces
├── Applicable rules
├── Assumptions
├── Manufacturing information
├── Validation results
├── Fusion reference
└── Change history
```

The exact schema should be designed by you after inspecting the project.

Keep it simple and extensible.

---

# 10. INTERFACE MODEL

Components must be able to describe how they connect to other components.

An interface may contain:

* interface ID
* parent component
* child component
* interface type
* location
* orientation
* mounting points
* contact surfaces
* clearance requirements
* interface status

Examples:

```text
NOSE ↔ FRONT_WING
MONOCOQUE ↔ NOSE
MONOCOQUE ↔ FLOOR
MONOCOQUE ↔ SUSPENSION
REAR_BODY ↔ REAR_WING
```

The purpose is not to build a perfect PLM system immediately.

The purpose is to allow the AI engineer to understand:

> "Where does this new component connect to the existing vehicle?"

---

# 11. FIA RULE SYSTEM

The project must eventually use official FIA technical regulations as a source of constraints.

Do not hard-code large amounts of regulatory text into prompts.

Instead, create a structured rule system.

A rule should conceptually contain:

```text
Rule ID
Category
Description
Requirement
Applicable component
Constraint type
Constraint value
Unit
Validation method
Source
Regulation version
Verification status
```

Important:

Never claim:

> "FIA compliant"

unless the relevant rule has actually been checked.

Use statuses such as:

* VERIFIED
* NOT_VERIFIED
* NON_COMPLIANT
* NOT_APPLICABLE
* ASSUMPTION

The project should use the current official FIA regulation version available during implementation.

Do not invent rules.

If a rule cannot be reliably interpreted or validated, mark it as NOT_VERIFIED.

---

# 12. ENGINEERING WORKFLOW

Every design task should eventually follow this workflow:

## STEP 1 — Requirement Extraction

Convert the user's natural-language request into structured requirements.

Example:

```text
Part:
Front Wing

Purpose:
Aerodynamic front bodywork

Target:
F1 concept vehicle

Regulation:
Applicable FIA technical regulations

CAD:
Parametric Fusion model
```

---

## STEP 2 — Missing Information

Determine whether important information is missing.

Examples:

* interface location
* desired dimensions
* manufacturing process
* material
* clearance
* aerodynamic target
* parent component

Do not silently invent critical information.

If information is missing:

1. ask the user if necessary, OR
2. make a clearly stated assumption if the project rules permit it.

---

## STEP 3 — Existing Context

Before designing a new component, inspect:

* existing vehicle state
* existing components
* relevant interfaces
* coordinate system
* previous revisions
* applicable rules

The agent must avoid designing components in isolation when relevant context exists.

---

## STEP 4 — Assumptions

Create explicit assumptions.

Example:

```text
A01:
Concept-level aerodynamic design.

A02:
Carbon composite assumed.

A03:
No CFD optimization in current phase.

A04:
Nominal geometry only.
```

Assumptions must be visible in the final report.

---

## STEP 5 — Engineering Plan

Before CAD execution, create a short engineering plan.

Example:

```text
1. Read applicable constraints.
2. Locate nose interface.
3. Establish wing reference geometry.
4. Create parametric sketches.
5. Build main surfaces/features.
6. Validate dimensions.
7. Check interface.
8. Check manufacturability.
```

---

# 13. CAD GENERATION

The agent must use Fusion 360 through the available Fusion MCP integration.

Do not create meaningless geometry.

Models should be:

* parametric
* structured
* understandable
* editable
* feature-based where practical
* meaningfully named

Parameters should have meaningful names.

Features and sketches should have meaningful names.

Avoid creating a single arbitrary imported mesh unless explicitly required.

The CAD model should remain editable.

---

# 14. CAD VALIDATION

After creating a component, inspect the result.

At minimum, where supported:

* bounding box
* dimensions
* volume
* body count
* feature health
* sketch status
* parameter values
* interface positions

If something is wrong:

1. identify the issue
2. attempt a correction
3. revalidate

Do not blindly continue after a CAD operation fails.

---

# 15. MANUFACTURABILITY

The first manufacturability system should be basic.

Do not attempt to create a complete manufacturing expert system.

Depending on the chosen manufacturing process, check obvious issues such as:

* unreasonable wall thickness
* impossible/very tight geometry
* inaccessible features
* unnecessary sharp internal corners
* extreme complexity
* obvious tool-access problems
* inconsistent symmetry where symmetry is expected

Every manufacturing conclusion should clearly distinguish:

* verified
* assumed
* not checked

---

# 16. AGENT DECISION-MAKING

The agent must not blindly execute every instruction.

For each task it should conceptually decide:

```text
What do I know?
What do I not know?
What constraints apply?
What existing geometry matters?
What assumptions are required?
What should I do next?
How can I verify the result?
```

This decision process is central to the project.

---

# 17. ITERATIVE DESIGN

The architecture must support future iteration.

Example:

User:

> "The front wing is too large."

Agent should eventually be able to:

1. identify the current component
2. inspect its parameters
3. identify affected interfaces
4. modify relevant parameters
5. regenerate geometry
6. validate again
7. update revision
8. report changes

Do not implement every advanced capability now, but design the architecture so this workflow is possible later.

---

# 18. ASSEMBLY VISION

The final long-term workflow is:

```text
Requirements
↓
Monocoque
↓
Nose
↓
Front Wing
↓
Floor
↓
Sidepods
↓
Engine Cover
↓
Rear Body
↓
Rear Wing
↓
Suspension
↓
Wheels
↓
Other components
↓
Fusion Assembly
```

Each component should be independently manageable.

The final vehicle should be assembled using the common vehicle coordinate system and component interfaces.

The agent should eventually understand relationships between components.

---

# 19. DEVELOPMENT STRATEGY

Do NOT attempt to build the complete F1 vehicle immediately.

Develop vertically.

First prove:

```text
USER REQUEST
↓
REQUIREMENT ANALYSIS
↓
ASSUMPTIONS
↓
DESIGN PLAN
↓
FUSION
↓
VALIDATION
```

with one simple component.

Then expand.

Suggested progression:

### Prototype 1

Simple engineering bracket.

Purpose:
Prove agent → planning → Fusion → validation.

### Prototype 2

F1 mounting/interface component.

Purpose:
Prove vehicle coordinate system + interfaces.

### Prototype 3

Nose.

Purpose:
Prove real vehicle context.

### Prototype 4

Front wing.

Purpose:
Prove regulatory + multi-component engineering reasoning.

### Prototype 5

Multiple components.

Purpose:
Prove persistent vehicle state.

### Prototype 6

Full concept assembly.

Purpose:
Demonstrate the complete system.

---

# 20. FUTURE EXTENSIONS

Design the system so the following can be added later:

### Phase 7

Simulation / analysis

* CFD
* FEA
* structural analysis
* thermal analysis

### Phase 8

AI-driven design optimization

* evaluate results
* modify geometry
* rerun analysis
* compare designs

### Phase 9

Technical drawings

* create drawings
* dimensions
* annotations
* tolerances

### Phase 10

BOM

* component list
* materials
* quantities
* revisions

These are NOT required for the first MVP.

---

# 21. IMPORTANT ENGINEERING SAFETY / ACCURACY PRINCIPLE

The system is a concept engineering agent.

It must never falsely represent its output as:

* officially FIA homologated
* race-ready
* physically validated
* structurally safe
* production-ready

unless those claims are actually supported by appropriate verification.

Always distinguish between:

* AI-generated design
* rule checked
* engineering assumption
* geometry validated
* simulation validated
* human verified

---

# 22. YOUR FIRST TASK

Before writing substantial code:

1. Inspect the entire existing project directory.
2. Inspect the existing folder structure.
3. Inspect available Python environment.
4. Inspect installed packages.
5. Determine how Fusion MCP is currently exposed.
6. Determine what Fusion operations are available.
7. Check whether any existing files/scripts already exist.
8. Do not overwrite existing useful work.
9. Identify missing dependencies.
10. Create a short architecture proposal inside `docs/`.

Then create:

```text
docs/
    architecture.md
    development_plan.md
```

The documents should explain the architecture in practical terms.

Do NOT create unnecessary complexity.

---

# 23. THEN BUILD THE MVP

After inspection and architecture definition, implement the first working vertical slice.

The MVP must demonstrate:

```text
Natural language request
        ↓
Requirement extraction
        ↓
Missing information detection
        ↓
Assumptions
        ↓
Engineering plan
        ↓
Fusion CAD execution
        ↓
Basic validation
        ↓
Result report
```

The MVP should work with one simple engineering component before attempting the F1 vehicle.

The system must be runnable.

Do not stop after generating architecture documents.

---

# 24. TESTING

Create tests for the deterministic parts of the system.

At minimum test:

* component data validation
* interface data validation
* rule data validation
* coordinate transformations
* validation status handling
* assumption handling
* component registration

Do not test only whether files exist.

Test actual behavior.

---

# 25. DOCUMENTATION

Create a clear README explaining:

1. What the project is.
2. What an AI Engineering Agent means in this project.
3. Architecture.
4. Technology stack.
5. How to run the project.
6. How Fusion integration works.
7. How components are represented.
8. How rules are represented.
9. Current limitations.
10. Future roadmap.

Keep the README understandable to an engineer who is not a software specialist.

---

# 26. DEVELOPMENT PRINCIPLES

Follow these principles throughout development:

### Simplicity

Do not over-engineer the first version.

### Modularity

Each subsystem should have a clear responsibility.

### Transparency

The agent should explain assumptions and validation results.

### Deterministic engineering

Use Python/code for calculations and checks where practical.

### AI for reasoning

Use Claude for interpretation, planning, orchestration, and engineering reasoning.

### CAD through tools

Use Fusion MCP for actual CAD execution.

### Persistent state

Do not rely on conversational memory for vehicle state.

### Incremental development

Build and test one capability at a time.

### Recoverability

A failed CAD operation must not silently corrupt project state.

### Traceability

Important decisions should be traceable to requirements, rules, assumptions, or existing geometry.

---

# 27. VERY IMPORTANT: DO NOT PRETEND

If something cannot currently be automated through the available Fusion MCP tools:

Do not fake it.

Do not create a mock implementation and pretend it controls Fusion.

Instead:

1. detect the limitation
2. document it
3. create a clean abstraction/interface
4. continue implementing everything that can be implemented
5. clearly identify the remaining integration point

The same principle applies to FIA validation and engineering calculations.

---

# 28. FINAL OBJECTIVE

The final project should evolve toward this capability:

A user gives the agent an engineering objective.

The agent:

* understands it
* gathers context
* identifies constraints
* detects missing information
* makes explicit assumptions
* plans the engineering work
* creates parametric CAD
* validates the design
* manages component relationships
* revises designs when required
* maintains vehicle state
* and eventually assembles multiple components into a complete F1 concept vehicle.

The ultimate demonstration should be:

> A user asks the AI Engineering Agent to create an F1 concept vehicle under defined FIA technical constraints, and the agent progressively designs the vehicle component-by-component in Fusion 360, maintains relationships between the components, validates the designs, and finally creates the vehicle assembly.

The F1 car is the demonstration.

The AI Engineering Agent is the actual project.

---

# 29. HOW YOU SHOULD WORK WITH ME

You are not expected to implement everything in one uncontrolled operation.

Work in stages.

After inspecting the project, report:

1. What already exists.
2. What is missing.
3. Proposed architecture.
4. What you will implement first.
5. Any technical limitations you discovered.

Then implement the first vertical slice.

After each major milestone:

* run tests
* verify the result
* update documentation
* report what works
* report what does not work
* propose the next concrete step

Do not ask unnecessary questions if a reasonable engineering assumption can be made.

When an assumption materially affects architecture or final behavior, stop and ask.

The priority is:

**WORKING ENGINEERING AGENT > COMPLEX ARCHITECTURE**

Start by inspecting the project now.
