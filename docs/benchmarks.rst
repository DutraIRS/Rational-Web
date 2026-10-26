Benchmarks
==========

Run them yourself::

   python benchmarks/run.py            # ~30 s, prints a Markdown report
   python benchmarks/run.py --quick

Method
------

Requests go through the full ASGI stack **in-process** (``httpx.ASGITransport``):
routing, rendering, CSS compilation, sessions and JSON — on one CPU core, with no
network and no HTTP server. The baseline is plain FastAPI returning an equivalent,
*pre-built* HTML string, i.e. the floor for "Python serving HTML through FastAPI".
A real deployment adds the server's parsing and socket cost to every row equally.

Results
-------

Python 3.14.7, Windows 11, Intel Core (Tiger Lake), single process.

.. list-table::
   :header-rows: 1

   * - Scenario
     - Requests/s
     - p50
     - p95
   * - FastAPI baseline: prebuilt HTML string
     - 2,651
     - 0.35 ms
     - 0.56 ms
   * - Rational: static page
     - 1,942
     - 0.48 ms
     - 0.76 ms
   * - Rational: interactive page (counter)
     - 1,390
     - 0.66 ms
     - 0.88 ms
   * - Rational: 100-row table page
     - 390
     - 2.39 ms
     - 2.91 ms
   * - Rational: event round trip (click → patch)
     - 1,390
     - 0.69 ms
     - 0.92 ms

.. list-table::
   :header-rows: 1

   * - Micro-benchmark
     - Result
   * - Render + serialize a 1,000-row keyed table
     - 18.4 ms
   * - Compile a new ``Style`` (cold)
     - 13.8 µs
   * - Compile a seen ``Style`` (cached)
     - 0.3 µs

.. list-table::
   :header-rows: 1

   * - Bytes on the wire
     - Raw
     - gzip
   * - ``runtime.js`` (interactive pages only)
     - 28.5 KiB
     - 8.3 KiB
   * - ``islands.js`` (pages with client components only)
     - 34.7 KiB
     - 10.1 KiB
   * - Theme CSS (immutable, cached)
     - 4.3 KiB
     - 1.2 KiB
   * - Counter event response
     - 0.3 KiB
     - 0.2 KiB
   * - Dashboard example page
     - 12.5 KiB
     - 2.9 KiB

Reading the numbers
-------------------

* A static page costs about 0.13 ms more than returning a prebuilt string: Rational keeps
  ~73% of raw FastAPI throughput while rendering components and compiling CSS.
* An interaction costs well under a millisecond of server time; network latency dominates.
* Cost grows with the number of elements, ≈18 µs per element including styling. Very
  large pages (thousands of rows) should paginate or virtualize, as in any SSR framework.
* The browser downloads about 8 KiB of JavaScript, once, and only for interactive pages
  (about 10 KiB more on pages with client components).

Is it "blazingly fast"? It is Python, so no — not in the sense of Rust or Go servers. It
is designed so that the framework is never the bottleneck of a typical page, and so that
the browser does very little work. Profiling-driven optimizations so far: caching each
``Style``'s identity at construction (cached style lookups went from 20 µs to 0.3 µs)
and caching tag/attribute-name validation.
