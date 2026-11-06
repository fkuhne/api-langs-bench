---
name: next-step
description: Prepare the plan's next step. Read the first unticked step in spec/plan.md and everything it touches, then lay out its choices with evidence and a recommendation for the owner to pick, before writing any code. Use when the owner asks what's next, or to start the next step.
---

# Prepare the next step

1. **Find the step:** the first unticked one in `spec/plan.md`. Read what it touches:
   - `spec/product.md`, and the rows of `spec/requirements.md` it serves;
   - the decision records it names, from `spec/decisions/`;
   - the notes in `docs/` it relies on or will check;
   - the code it will change.
2. **If the step has no design choices,** say in a few lines what it will build or measure, and how it will be checked. Then ask whether to go ahead.
3. **Otherwise, lay out each choice:**
   - two to four options, each with what it costs and what it gives, including the time, memory and disk it needs;
   - the evidence: measure, run or read the documentation where you can, and say what comes from memory alone;
   - a recommendation, with its reason.

   Keep it short; a table often helps.
4. **Stop, and let the owner pick.** Write no code and no record before the pick.
5. **After the pick:**
   - Record the decision, with the `decide` skill.
   - Build the step in small commits. Each is a coherent increment, and none references a file that arrives later.
   - Run it on the machine its record names, and show the real output: scores, time, peak memory, disk use.
   - Write down what it measured in `docs/`, with the command, the settings and the machine. Move any answered open question into the notes, with its source.
   - Tick the step in the commit that finishes it.
   - Explain what was built or learned and why, with links to the lines. Ask before starting the next step.
