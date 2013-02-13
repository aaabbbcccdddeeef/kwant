# Copyright 2011-2013 kwant authors.
#
# This file is part of kwant.  It is subject to the license terms in the
# LICENSE file found in the top-level directory of this distribution and at
# http://kwant-project.org/license.  A list of kwant authors can be found in
# the AUTHORS file at the top-level directory of this distribution and at
# http://kwant-project.org/authors.

__all__ = ['solve', 'ldos', 'wave_func']

# MUMPS usually works best.  Use SciPy as fallback.
try:
    from . import mumps as smodule
except ImportError:
    from . import sparse as smodule

hidden_instance = smodule.Solver()

solve = hidden_instance.solve
ldos = hidden_instance.ldos
wave_func = hidden_instance.wave_func