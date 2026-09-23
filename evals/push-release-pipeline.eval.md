# Eval Spec: push-release-pipeline-skill

Each rollout builds a throwaway repository with a synthetic build, a bare origin and
a fake release provider, then runs the real pipeline against one scenario. Nothing
touches the network or a real provider, so the suite is safe to re-run.

The criteria grade the invariants that must hold in every scenario, whether the run
published or refused: a release is never reported published unless its closed-loop
read-back passed, a tag never survives a run that did not publish, and a published run
records its provenance. They call scripts/eval_check.py rather than grep so they
behave identically on Windows, where grep is only present when Git's usr/bin is on
PATH.

```json
{
  "skill": "push-release-pipeline-skill",
  "run": "python3 scripts/eval_harness.py --scenario {input} --output {output} || python scripts/eval_harness.py --scenario {input} --output {output}",
  "criteria": [
    {
      "id": "harness-ran",
      "text": "The harness produced a verdict with a numeric exit code",
      "type": "command",
      "cmd": "python3 scripts/eval_check.py {output} harnessRan || python scripts/eval_check.py {output} harnessRan"
    },
    {
      "id": "closed-loop-consistent",
      "text": "A release is never reported as published unless its closed-loop read-back passed",
      "type": "command",
      "cmd": "python3 scripts/eval_check.py {output} closedLoopConsistent || python scripts/eval_check.py {output} closedLoopConsistent"
    },
    {
      "id": "no-orphan-tag",
      "text": "A tag never survives a run that did not publish",
      "type": "command",
      "cmd": "python3 scripts/eval_check.py {output} noOrphanTag || python scripts/eval_check.py {output} noOrphanTag"
    },
    {
      "id": "provenance-complete",
      "text": "A published run records the commit, tree and artifact hash",
      "type": "command",
      "cmd": "python3 scripts/eval_check.py {output} provenanceComplete || python scripts/eval_check.py {output} provenanceComplete"
    },
    {
      "id": "scenario-identified",
      "text": "The verdict names the scenario it graded",
      "type": "command",
      "cmd": "python3 scripts/eval_check.py {output} scenarioIdentified || python scripts/eval_check.py {output} scenarioIdentified"
    }
  ],
  "golden": [
    {
      "id": "clean-release",
      "input": "golden/clean-release/input.json",
      "expected": null,
      "split": "val",
      "expected_status": "pending-first-green",
      "compare": "none"
    },
    {
      "id": "dirty-tree-refused",
      "input": "golden/dirty-tree-refused/input.json",
      "expected": null,
      "split": "val",
      "expected_status": "pending-first-green",
      "compare": "none"
    },
    {
      "id": "version-collision-refused",
      "input": "golden/version-collision-refused/input.json",
      "expected": null,
      "split": "val",
      "expected_status": "pending-first-green",
      "compare": "none"
    },
    {
      "id": "tracked-file-touched-refused",
      "input": "golden/tracked-file-touched-refused/input.json",
      "expected": null,
      "split": "val",
      "expected_status": "pending-first-green",
      "compare": "none"
    },
    {
      "id": "corrupted-upload-rolled-back",
      "input": "golden/corrupted-upload-rolled-back/input.json",
      "expected": null,
      "split": "test",
      "expected_status": "pending-first-green",
      "compare": "none"
    }
  ]
}
```
