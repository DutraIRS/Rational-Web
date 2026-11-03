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
     - 4,659
     - 0.18 ms
     - 0.38 ms
   * - Rational: static page
     - 1,918
     - 0.43 ms
     - 0.96 ms
   * - Rational: interactive page (counter)
     - 1,322
     - 0.59 ms
     - 1.37 ms
   * - Rational: 100-row table page
     - 342
     - 2.70 ms
     - 3.93 ms
   * - Rational: event round trip (click → patch)
     - 1,454
     - 0.60 ms
     - 1.09 ms

.. list-table::
   :header-rows: 1

   * - Micro-benchmark
     - Result
   * - Render + serialize a 1,000-row keyed table
     - 23.2 ms
   * - Compile a new ``Style`` (cold)
     - 24.3 µs
   * - Compile a seen ``Style`` (cached)
     - 0.7 µs

.. list-table::
   :header-rows: 1

   * - Bytes on the wire
     - Raw
     - gzip
   * - ``runtime.js`` (interactive pages only)
     - 30.1 KiB
     - 8.8 KiB
   * - ``islands.js`` (pages with client components only)
     - 35.7 KiB
     - 10.4 KiB
   * - Theme CSS (immutable, cached)
     - 5.5 KiB
     - 1.6 KiB
   * - Counter event response
     - 0.1 KiB
     - 0.1 KiB
   * - Dashboard example page
     - 12.4 KiB
     - 2.9 KiB

Reading the numbers
-------------------

* A static page costs about 0.25 ms more than returning a prebuilt string: Rational keeps
  ~41% of raw FastAPI throughput while rendering components and compiling CSS.
* An interaction costs about a millisecond of server time or less; network latency dominates.
* Cost grows with the number of elements, ≈23 µs per element including styling. Very
  large pages (thousands of rows) should paginate or virtualize, as in any SSR framework.
* The browser downloads about 9 KiB of JavaScript, once, and only for interactive pages
  (about 10 KiB more on pages with client components).

Is it "blazingly fast"? It is Python, so no — not in the sense of Rust or Go servers. It
is designed so that the framework is never the bottleneck of a typical page, and so that
the browser does very little work. Profiling-driven optimizations so far: caching each
``Style``'s identity at construction (cached style lookups went from 20 µs to under 1 µs)
and caching tag/attribute-name validation.
