# Host freeze, 2026-10-21 ~17:41–18:27

Kyojin 1.6, ctx=262144, sessions=1, vision on, `EXL3_NGRAM_STREAM` unset.

## What the run recorded, in order

1. Seven seconds before the start, page cache dropped: `avail_gib 107`
   (`drop-before.txt`, copied verbatim from the attempt directory).
2. During the target load:

       [ngram] table mode trellis_ram: 320001536 rows, host MemAvailable 76.7 GiB at load
       (RAM mode needs table + 48 GiB; disk mode = every prefill chunk reads its rows from
       the file, a busy disk or a cold page cache stalls it)

3. `READY ... (start-up 644 s)`, then the benchmark's first prefill line (1,218.7 tok/s),
   then nothing. The machine stopped responding, no more records were written, and it had
   to be rebooted.

## The rule, and where its input comes from

`exllamav3/modules/ngram_embedding.py`, in `load()`:

    avail = host_memory_available()
    tbl   = self.num_rows * (words_per_row(self.K) * 2 if quantized else ROW_DIM * 2)
    stream_from_disk = avail is None or avail < tbl + (48 << 30)

The table is 320,001,536 rows, about 30 GiB at this pack's row width, so the threshold is
about 30 + 48 = 78 GiB.

**The logged 76.7 GiB is not the number the rule used.** The `[ngram]` line takes its own
measurement at the end of `load()`, after the table has already been allocated into system
RAM. Subtract the resident table and the rule saw roughly 107 GiB — the same figure the
page-cache drop recorded — against a 78 GiB threshold. It chose RAM. Measured again a
moment later, the same call returned 76.7 GiB, i.e. *below* the threshold it had just
passed. That is why the quoted log line looks self-contradictory: two measurements of the
same quantity, before and after the allocation, and only the second one is printed.

**The margin is a constant, and the pack is not.** The 89 GB of weights land after this
module loads, and at 262144 positions the KV pool is another 7.7 GiB. A fixed 48 GiB
reserve cannot make a pre-load snapshot safe on a 128 GiB host with this pack.

The pack plus the table plus KV do not fit. This is not "the table was swapped out":
the engine reports 4 KiB of its own pages in swap at READY, so the memory was simply
gone.

The project's own reference loader keeps the same table file-backed:
`tools/strix_halo/load_qwen.py` — "The 32.6 GB n-gram/PLE table stays file-backed
(`trellis_disk` mode)".

## The documentation says the opposite of the code

`doc/env_vars.md` lists `EXL3_NGRAM_STREAM` as **(default: `1`)**, "stream ... instead of
loading the whole table into system RAM", with "set to `0` to hold the table in RAM".
`exllamav3/model/config.py` leaves the value `None` when the variable is unset, and `None`
means *auto* — the path that chose RAM here. A user who leaves the variable unset because
the documentation says streaming is the default gets the opposite of what the
documentation says.

## Fix applied

`EXL3_NGRAM_STREAM: "1"` in both overlays, forced rather than inferred. With it set, the
table is file-backed and the same configuration runs.

## Not claimed

Which of the three is the defect — the fixed margin, the timing of the measurement, or the
documentation — is the maintainer's call. What is reproducible on this machine is that the
auto path picked RAM for a 30 GiB table in front of an 89 GiB pack, and the host did not
survive it.
