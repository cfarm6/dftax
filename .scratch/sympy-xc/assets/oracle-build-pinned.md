# Pinned Libxc default-parameter oracle build evidence

- Pin: `7d236789c2a4521270eeaa41d06e0d721ef56abd` (`git -C /tmp/libxcsrc/libxc rev-parse HEAD`, clean, shared source unmodified)
- Prefix: `/tmp/xcoracle-po`; build dir: `/tmp/xcoracle-build`; venv: `/tmp/xcoracle-po/venv`
- Site-packages: `/tmp/xcoracle-po/cpython-3.13-linux-x86_64-gnu/lib/python3.13/site-packages` (must precede sys.path)

## Tool versions

- cmake 3.31.6, gcc Ubuntu 15.2.0-4ubuntu4, Python 3.13.7 (venv), ninja 1.12.1, numpy 2.5.3 (venv)

## Exact commands (in order)

```
python3 -m venv /tmp/xcoracle-po/venv
/tmp/xcoracle-po/venv/bin/pip install numpy
cmake -S /tmp/libxcsrc/libxc -B /tmp/xcoracle-build -G Ninja \
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/tmp/xcoracle-po \
  -DBUILD_SHARED_LIBS=ON -DENABLE_PYTHON=ON -DMAXORDER=0 -DBUILD_TESTING=OFF
cmake --build /tmp/xcoracle-build
cmake --install /tmp/xcoracle-build
cp /tmp/xcoracle-po/lib/libxc.so.15 \
  /tmp/xcoracle-po/cpython-3.13-linux-x86_64-gnu/lib/python3.13/site-packages/pylibxc/libxc.so
```

No maple2c/sympy2c regeneration; generated `maple2c` used as-is; no PySCF; no production edits.

## Identity

- `pylibxc.__version__` / `xc_version_string()` = 7.1.2
- `pylibxc.__file__` = `.../site-packages/pylibxc/__init__.py` (prefix above)
- `get_core_path()` = `.../site-packages/pylibxc` (local dir; `core` loads `pylibxc/libxc.so`, now a real copy of installed `lib/libxc.so.15`, not a build-tree symlink)
- md5 installed `lib/libxc.so.15` = `423ecfdd744ce317432a4919fb0524a5` (matches pylibxc copy)
- Note: `/tmp/xcoracle-build/libxc.so.15` md5 `fe2fdbf6e3415be899425641c62d0870` differs (install-time relink/rpath); oracle uses the installed copy.

## Smoke (reusable invocation)

```
cd /tmp/libxcsrc/libxc
SP=/tmp/xcoracle-po/cpython-3.13-linux-x86_64-gnu/lib/python3.13/site-packages
LD_LIBRARY_PATH=/tmp/xcoracle-po/lib \
PYTHONPATH=/tmp/libxcsrc/libxc/scripts/sympy2c:/tmp/sympyenv:$SP \
/tmp/xcoracle-po/venv/bin/python -c "
import sys; sys.path.insert(0, '$SP')
from build_info import _built_parameters
print(_built_parameters('lda_c_1d_css'))"
```

Cwd matters: `build_info._resolve_source` reads the pinned tree relatively.

## Observed smoke output

```
core path: .../site-packages/pylibxc
lib version: 7.1.2
number: 18 name: Casula, Sorella & Senatore kind: 1
nkeys: 4
params_a_bb = 1.0
params_a_ferro = [5.24, 0.0, 1.568, 0.12856, 0.003201, 2.0, 3.0, 0.0538, 1.56e-05, 2.958]
params_a_interaction = 1.0
params_a_para = [18.4, 0.0, 7.501, 0.10185, 0.012827, 2.0, 3.0, 1.511, 0.258, 4.424]
```

`_built_parameters('lda_c_1d_css')` returns initialized table defaults: PASS (4 keys, para/ferro 10-vectors).

## Independent runtime check

From the repository root:

```bash
env LD_LIBRARY_PATH=/tmp/xcoracle-po/lib \
  PYTHONPATH=/tmp/xcoracle-po/cpython-3.13-linux-x86_64-gnu/lib/python3.13/site-packages \
  /tmp/xcoracle-po/venv/bin/python -c \
  'import pylibxc; from pylibxc import core; print("version:",pylibxc.__version__); print("loaded library:",core._name); print("registered identities:",len(pylibxc.util.xc_available_functional_names()))'
```

Observed output:

```text
version: 7.1.2
loaded library: /tmp/xcoracle-po/cpython-3.13-linux-x86_64-gnu/lib/python3.13/site-packages/pylibxc/libxc.so
registered identities: 725
```

Runtime census reconciliation:

```bash
env LD_LIBRARY_PATH=/tmp/xcoracle-po/lib \
  PYTHONPATH=/tmp/xcoracle-po/cpython-3.13-linux-x86_64-gnu/lib/python3.13/site-packages \
  /tmp/xcoracle-po/venv/bin/python -c \
  'from collections import Counter; from pylibxc import util; names=util.xc_available_functional_names(); ids=[util.xc_functional_get_number(n) for n in names]; print("runtime names:",len(names),"unique names:",len(set(names)),"unique IDs:",len(set(ids))); print("multi-name IDs:",sum(c>1 for c in Counter(ids).values()))'
```

Observed:

```text
runtime names: 725 unique names: 709 unique IDs: 709
multi-name IDs: 15
```

The runtime enumeration repeats canonical names: 725 returned entries are
not 725 distinct candidates. The audit must retain the source registry's
alias keys separately and reconcile the 709 distinct registered identities.

This `MAXORDER=0` build supplies initialized defaults and energy evaluation,
not a derivative-order numerical oracle.

## Energy smoke

```bash
env LD_LIBRARY_PATH=/tmp/xcoracle-po/lib \
  PYTHONPATH=/tmp/xcoracle-po/cpython-3.13-linux-x86_64-gnu/lib/python3.13/site-packages \
  /tmp/xcoracle-po/venv/bin/python -c \
  'import numpy as np,pylibxc; names=("lda_x","gga_x_pbe","mgga_x_r2scan","mgga_xc_cc06","lda_c_1d_css"); [(print(n,"spin",s,"epsilon",pylibxc.LibXCFunctional(n,s).compute({"rho":np.array([0.5] if s==1 else [0.5,0.3]),"sigma":np.full(1 if s==1 else 3,0.1),"lapl":np.full(s,0.05),"tau":np.full(s,0.4)},do_exc=True,do_vxc=False)["zk"].ravel().tolist())) for n in names for s in (1,2)]'
```

Observed output (Libxc `zk`, per-electron epsilon):

```text
lda_x spin 1 epsilon [-0.586194481347579]
lda_x spin 2 epsilon [-0.6951959497930993]
gga_x_pbe spin 1 epsilon [-0.5883191096988102]
gga_x_pbe spin 2 epsilon [-0.6983207016868604]
mgga_x_r2scan spin 1 epsilon [-0.65076419561809]
mgga_x_r2scan spin 2 epsilon [-0.7766835325850352]
mgga_xc_cc06 spin 1 epsilon [-0.6516257278269045]
mgga_xc_cc06 spin 2 epsilon [-0.7629222085338432]
lda_c_1d_css spin 1 epsilon [-0.019835332804731685]
lda_c_1d_css spin 2 epsilon [-0.009532997457988636]
```

The first four agree with the previously recorded source-only sample values
to their displayed 12 decimal places. This is a smoke, not catalog-wide
numerical or autodiff acceptance.
