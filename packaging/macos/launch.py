"""Entry point of the frozen macOS app (PyInstaller runs this file)."""
from amberfader.embedded.__main__ import main

raise SystemExit(main())
