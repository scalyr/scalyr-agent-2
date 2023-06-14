import pathlib as pl

import venv


class WrappedPythonEnvBuilder(venv.EnvBuilder):
    def setup_python(self, context):
        executables_dir = pl.Path(context.executable).parent
        context.executable = executables_dir / "python3"
        super(WrappedPythonEnvBuilder, self).setup_python(context=context)


venv.EnvBuilder = WrappedPythonEnvBuilder

import venv.__main_original__