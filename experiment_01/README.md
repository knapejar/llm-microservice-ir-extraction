# Experiment 01: per-file LLM extraction vs. CIMET

Runs the Appendix A prompt (`prompt_appendix_a.txt`, verbatim) one file at a
time, temperature 0, and scores the result against a manual ground truth, next
to the deterministic CIMET 1.2.1 baseline.

Systems: spring-cloud-movie-recommendation, xs2a, geoserver-cloud.
Results: `out/eval*.summary.md`, interactive: `out/viewer.html`.

## Run

```bash
python llm_extract.py --model gemini-3.5-flash-lite --repo clone/<system> --system-name <system>
python llm_extract.py --model <model> --base-url <openai-compatible url> ...   # LM Studio, hosted gpt-oss-120b
python evaluate.py    --pred out/llm_ir.<...>.json --gt groundtruth/<system>.gt.json
python summarize.py   --gt groundtruth/<system>.gt.json --pred <files...> --out out/eval.<system>.summary.md
python build_viewer.py --cimet-dir <dir with IR-xs2a.json>
```

Keys: `keys.txt` (git-ignored, one per line) or `--keys`; `$LLM_API_KEY` for
`--base-url`. Keys rotate on 429 and are never written to outputs.

## How it is scored

- **Ground truth** (`groundtruth/`): manually labelled, protocol in its README.
- **Service** of an LLM entry is resolved from its file path, since the
  Appendix A schema has no service field.
- **Matching levels** M1 (exact path), M2 (normalized path, the reported one),
  M3 (path, any verb), M4 (class + method).
- **Surplus split:** a *role-separation error* is an outbound call reported as
  an inbound endpoint; a *hallucination* matches nothing at all.

## Limits

- One run per model, no repeat-run stability measure.
- xs2a with hosted gpt-oss-120b: the provider's free tier rejected 6 of the 8
  large API files as too large, so that score measures the limit, not the model.
- `compare.py` / `out/*.report.md` are the first run, scored against CIMET
  instead of the ground truth.

## Files

| file | what it is |
|---|---|
| `llm_extract.py` | per-file extraction |
| `evaluate.py`, `summarize.py` | scoring per run and per system |
| `groundtruth/` | ground truth for 3 systems + `validate.py` |
| `baseline/IR-*.cimet.json` | CIMET output (the 63 MB xs2a IR is not committed) |
| `build_viewer.py`, `viewer.template.html` | build `out/viewer.html` |
| `out/llm_ir.*.json` | raw LLM output + per-file log (tokens, latency) |
