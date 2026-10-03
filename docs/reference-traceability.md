# Reference preservation and numerical corrections

Input documents were treated as implementation references. The user explicitly
adopted `Codex_Power_System_Digital_Twin_Build_Prompt.md` as the requirements;
the handbook/ZIP supply baseline models and examples rather than field proof.

The ZIP was extracted only after checking every destination stays beneath the
named `reference` directory. The original project is retained byte-for-byte;
`docs/evidence/reference-comparison.json` records the archive SHA256, all 48 file
comparisons and source hashes/diffs. The handbook was read/extracted to
`reference/handbook.txt`; the original DOCX and ZIP remain in Downloads.

All 16 `tl_twin` Python modules were reused under `src/tl_twin`. Fifteen are
unchanged. `twin.py` adds only an optional solver callback so the same time,
quality, topology and validation-role gates can evaluate electrical sections.
Default behavior is preserved and the 30 original tests are also retained in
`tests/test_reference.py`. The original 30-test suite was executed before
application refactoring. The entire new application suite includes those tests.

Application refinements live in `grid_twin`:

* Stale/future live boundaries produce DATA_UNAVAILABLE and no prediction/raw
  residual. The reference could keep a computed value with stale flags; the
  application prevents it appearing as a current prediction.
* Isolated snapshots store independent ABCD checks and fail on disagreement using
  the original justified `rel=1e-7, abs=1e-7` limits for kV/A/MW/MVAr quantities.
  Section cascades multiply the nominal-pi ABCD matrices, and compare a separately
  assembled pandapower section network without weakening tolerances.
* Meter loss uncertainty supports an explicitly supplied correlation coefficient,
  instead of assuming independence for every meter pair.
* Published effective-date timelines, native UTC/JSONB persistence, transactional
  jobs, project roles, plugin contributions and the UI are new platform layers.
  The legacy reference storage's `create_all` initialization is not used by the
  application schema or migrations.

The regression case remains 132kV, 50Hz, 65km, R=.08ohm/km, X=.35ohm/km,
C=9nF/km, G=0, one circuit, illustrative .60kA rating, Vs=132.1kV,
receiving P=66.8MW and Q=13.5MVAr. Expected Vr=126.697514kV,
Is=307.531842A, Ir=310.556265A, sending P=68.292348MW/Q=16.950410MVAr,
loss=1.492348MW, net reactive absorption=3.450410MVAr and loading=51.759378%.
These remain synthetic software targets, not actual-line error thresholds.

R/X/C/G are per-phase positive-sequence per km for one full circuit. Circuits
scale series/shunt branches and rating convention; subconductor bundle metadata
does not imply another complete circuit. Measured conductor temperature applies
R(T)=Rref[1+alpha(T-Tref)] exactly once. Ambient temperature is not substituted.
Receiving P/Q is total three-phase power leaving the selected branch; pandapower
`p_to_mw/q_to_mvar` signs are transformed explicitly. Net reactive absorption can
be negative under charging, and reverse flow does not swap terminal identities.

Official API references inspected during implementation (3 October 2026):
[pandapower 3.5.5 line parameters/model](https://pandapower.readthedocs.io/en/latest/elements/line.html),
[FastAPI security](https://fastapi.tiangolo.com/tutorial/security/oauth2-jwt/),
[React Flow](https://reactflow.dev/learn),
[Alembic migrations](https://alembic.sqlalchemy.org/en/latest/tutorial.html),
[Paho manual acknowledgement/client API](https://eclipse.dev/paho/files/paho.mqtt.python/html/client.html),
and [Docker Compose](https://docs.docker.com/compose/).
