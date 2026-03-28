from importlib.metadata import PackageNotFoundError, version

try:
    PLUGIN_VERSION = version('inventree-import-plugin')
except PackageNotFoundError:
    PLUGIN_VERSION = '0.0.0-dev'
