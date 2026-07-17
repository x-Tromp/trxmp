"""Trxmp's bundled knowledge base: frequency-band vocabulary and a small
headphone correction catalog, shipped as data files rather than code.

That distinction is the entire point of this package. The original
Tauri/Rust prototype's headphone corrections lived in a Rust ``match``
statement — adding a headphone meant a code change, a recompile, a
release. Here they live in :mod:`headphones.yaml`, validated by
:mod:`catalog.py` through the same domain rules any user-built preset
has to pass. Extending the catalog is a data change; nothing about the
application has to know it happened.
"""
