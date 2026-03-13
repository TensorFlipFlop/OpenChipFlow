#!/bin/csh
#
# cocotb_vcs env bootstrap (csh/tcsh)
#
# Usage:
#   cd cocotb_vcs
#   source cfg_env.csh
#
# What it does:
# - Select gcc toolchain under $GCC_HOME (VCS/PLI build chain consistency)
# - Use Anaconda Python via PATH (Python 3.12.7 + cocotb packages preinstalled)
# - Load EDA tools via environment-modules (vcs/verdi)
#

setenv GCC_HOME /tools/hydora64/hdk-r7-9.2.0/22.10
set gcc_bin = "$GCC_HOME/bin"

# Python (Anaconda) - tested path (not managed by modules)
set anaconda_root = /tools/ctools/rh7.9/anaconda3/2024.10
set anaconda_bin = "$anaconda_root/bin"

set have_module = 0
alias module >& /dev/null
if ( $status == 0 ) then
  set have_module = 1
endif

if ( $have_module ) then
  module load vcs/2023.03-SP2
  module load verdi/2023.03-SP2
else if ( $?MODULESHOME && -x "$MODULESHOME/bin/modulecmd" ) then
  eval `"$MODULESHOME/bin/modulecmd" csh load vcs/2023.03-SP2`
  eval `"$MODULESHOME/bin/modulecmd" csh load verdi/2023.03-SP2`
else
  echo "[cfg_env.csh][INFO] module command not initialized; skip module loads."
  echo "[cfg_env.csh][INFO] If your site uses environment-modules, source its init script, then:"
  echo "                 module load vcs/2023.03-SP2"
  echo "                 module load verdi/2023.03-SP2"
endif

# GCC toolchain (path-based, not from modules)
if ( -x "$gcc_bin/gcc" ) then
  if ( "$PATH" !~ *"$gcc_bin"* ) then
    setenv PATH "$gcc_bin:$PATH"
  endif
  setenv CC "$gcc_bin/gcc"
  setenv CXX "$gcc_bin/g++"
else
  echo "[cfg_env.csh][WARN] gcc not found: $gcc_bin/gcc"
endif

set gcc_libs = ""
if ( -d "$GCC_HOME/lib" ) then
  set gcc_libs = "$GCC_HOME/lib"
endif
if ( -d "$GCC_HOME/lib64" ) then
  if ( "$gcc_libs" != "" ) then
    set gcc_libs = "$gcc_libs:$GCC_HOME/lib64"
  else
    set gcc_libs = "$GCC_HOME/lib64"
  endif
endif
if ( "$gcc_libs" != "" ) then
  if ( $?LD_LIBRARY_PATH ) then
    setenv LD_LIBRARY_PATH "$gcc_libs:$LD_LIBRARY_PATH"
  else
    setenv LD_LIBRARY_PATH "$gcc_libs"
  endif
endif

# Python (Anaconda) - path-based, not managed by modules
if ( -d "$anaconda_bin" ) then
  if ( "$PATH" !~ *"$anaconda_bin"* ) then
    setenv PATH "$anaconda_bin:${PATH}"
  endif
else
  echo "[cfg_env.csh][WARN] anaconda bin not found: $anaconda_bin"
endif
