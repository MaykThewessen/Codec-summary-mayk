# Codec-summary-mayk

Evaluating the best codec / compression / algorithm / file type for each use case, with a dashboard per domain showing the trade-offs and the optimum choice for each region.

Five maps, all measured in this repository rather than quoted from vendors. Start at **[docs/index.html](docs/index.html)**.

| Map | The short answer |
|---|---|
| **[Images](docs/image_codec_tradeoff_map.html)** | AVIF below visually lossless, JPEG XL above it. On flat graphics everything inverts and WebP lossless wins outright. |
| **[Video](docs/video_codec_tradeoff_map.html)** | VVC leads everywhere, with AV1 closer behind it than the literature suggests. HEVC is level with H.264 at 540p. |
| **[Audio](docs/audio_codec_tradeoff_map.html)** | Opus first in every listening test since 2011. Above roughly 128 kbps the format stops mattering. |
| **[Data formats](docs/data_format_tradeoff_map.html)** | Parquet to store, Feather for scratch, DuckDB when the question is a query. The real case against CSV is correctness, not speed. |
| **[Compression](docs/compression_tradeoff_map.html)** | zstd owns most of the plane. brotli takes web assets, lz4 takes the hot loop, xz survives only where its dictionary is exercised. |

Every page is a single self-contained file: fonts and data inlined, nothing fetched at runtime, light and dark themes, every chart with a table-view twin.

## Method

The maps agree with each other because they share a discipline. Each of these rules changed a headline number at least once.

1. **Compare at matched quality, not matched settings.** JPEG q80 and AVIF q80 are unrelated numbers, and so are HEVC CRF 23 and AV1 CRF 23. Every codec is swept on its own ladder, scored with a perceptual metric (SSIMULACRA2 for images, VMAF for video), then interpolated to a fixed quality target before anything is compared.
2. **Never let the sweep decide the answer.** If one codec's ladder stops earlier than another's, the comparison at that end measures your sweep rather than the codec. Extending the AVIF ladder moved the images crossover from 83 to 87. xz -6 and -9 emit byte-identical output until the corpus grows past their dictionary. Video CRF ladders are per clip, because two clips eight CRF steps apart would otherwise have made the result an artefact.
3. **Generate every sentence containing a number.** Numeric prose is derived from the measurement files at build time, so re-running a sweep cannot leave the text asserting something the charts no longer show.
4. **Say what could not be measured.** RAR, HE-AAC and bit-exact AVIF lossless have no usable encoder in this environment. They appear as explicitly tagged cited-or-absent entries, never as a plausible-looking number. VVC was in this list until an ffmpeg build with libvvenc turned up, at which point the whole video sweep was re-run on that one binary rather than merging results across toolchains.

## Selected findings

**Images** (924 encodes, 14 Kodak reference photographs plus a rendered UI, SSIMULACRA2)

- AVIF and JPEG XL swap places at SSIMULACRA2 87: below it AVIF is smaller, above it JPEG XL is.
- WebP lossless is 67.7% under optimised PNG on a screenshot, pixel-identical, and beats every lossy option at the same size.
- The efficient JPEG quality band is q75 to q85. A quality point costs 0.057 bpp at q75 and 0.611 bpp by q98.

**Video** (267 encodes, six encoders at 540p, 720p, 1080p, VMAF, all from one ffmpeg build)

- Against x264 at 1080p: VVC 47.5 to 59.0%, libaom-AV1 41.4 to 50.2%, SVT-AV1 37.2 to 49.6%, VP9 10.4 to 23.5%, HEVC 6.8 to 16.9%.
- VVC beats AV1 everywhere, by 9.5 to 17.6% against libaom. The direction matches the literature but the size does not: published work puts AV1 far further behind VVC than it lands here, and the page names the four reasons rather than presenting either as a correction.
- SVT-AV1 costs 3.6x less than libaom for near-identical efficiency, and at 1.82x x264 it is cheaper to encode than x265 while producing files about 38% smaller than x265's.
- "HEVC is 50% better" does not survive a perceptual metric: 16.9% at best, and level with or behind x264 at 540p.
- Normalising to bits per pixel per frame puts resolutions on one axis but not one curve: more pixels means more redundancy per pixel, so 4K benefits twice.

**Audio** (34 cited listening-test results, 408 encodes measured here)

- Opus leads every multiformat test since 2011 by margins clearing the confidence intervals.
- Measured bandwidth ranks Vorbis above AAC at 64 kbps; listeners ranked it below, twice. Keeping more treble badly loses to keeping less treble cleanly.
- Perceptual quality is never measured here, only cited. This environment has no listening panel and no validated perceptual metric.

**Data formats** (electricity price, power flow, weather and register corpora at two scales)

- Reading 3 of 41 columns from a 1.200.000 row table: Feather 23 ms, Parquet zstd 63 ms, CSV 5.78 s.
- Round-tripping dtypes, timezones, categoricals and nullable integers: Parquet and Feather lose 0 of 6 properties, CSV / gzipped CSV / JSON / xlsx each lose 5 of 6.
- Memory-mapping 393.7 MB of Arrow IPC took 2.0 ms and grew the process by 3.7 MB. Compressing the file removes the property entirely.

**Compression** (23 settings, 6 corpora, 414 timed round trips)

- zstd holds 5 of 7 frontier points on source code; gzip, xz and bzip2 hold none.
- zstd decompression is flat within 18% across levels 1 to 22 while compression speed falls 189x.
- `--long=27` took zstd -3 from 4.7x to 37.0x and made it 3x faster.

## Reproducing

Python 3.11+ and network access for the corpora. Full sweeps take several hours; raw results are committed under `data/`, so any page rebuilds without re-running them.

```bash
pip install pillow pillow-heif pillow-avif-plugin pillow-jxl-plugin ssimulacra2 \
            imageio-ffmpeg pyarrow duckdb polars pandas \
            zstandard brotli lz4 py7zr xlsxwriter openpyxl python-calamine

# rebuild any page from committed data
python3 scripts/build_page.py scripts/<domain>/page_template.html \
        docs/<domain>_map.html data/<domain>/page_data.json
```

Each domain's measurement scripts live in `scripts/<domain>/` and run in the order `make_corpora` or `fetch_*`, then `measure_*`, then `analyse`, then `make_prose`, then `build_page`. The images page predates the shared pipeline and assembles its data inside `build_page.py`.

### Layout

| Path | Contents |
|---|---|
| `docs/` | Built pages, self-contained. `index.html` is the hub. |
| `scripts/<domain>/` | Measurement, analysis, prose generation, and the page template. |
| `data/<domain>/` | Raw sweep output and derived analysis, as JSON. |
| `assets/fonts/` | Tektur, Instrument Sans, Geist Mono. SIL Open Font License, texts included. |
| `testdata/` | Corpora, fetched or generated by scripts. Gitignored. |

`CONTRIBUTING.md` documents the method rules, the validated colour palette, the mark specs and the verification steps for adding a sixth domain.

## Caveats

Stated on each page, repeated here because they bound what the numbers mean.

- **Encoders are not always the best available.** Image JPEG figures use stock libjpeg-turbo, not mozjpeg or jpegli. Audio AAC uses ffmpeg's native encoder, not Apple's or fdk. Both understate their format, and the direction is stated on the page. Video now measures six encoders including SVT-AV1 and libvvenc, so that gap is closed there.
- **Encoder builds matter more than expected.** Re-running the video sweep on a newer ffmpeg left x264 byte-identical, x265 within 1.1% and VP9 within 0.2%, but made libaom-AV1 24.6% smaller for the same picture. AV1's headline moved from 22.8-37.7% to 41.4-50.2% at 1080p almost entirely for that reason. Treat any codec comparison assembled from more than one toolchain with suspicion, including earlier versions of this one.
- **Corpora are small.** Reference photographs are 768x512; video clips are 3 seconds at up to 1080p, with no 4K source available and no upscaling done.
- **Timings are noisy.** The data-format and compression benchmarks ran on a shared container under load from sibling jobs. Both report medians with repeat counts, and both tell readers what size of difference to treat as noise.
- **Some formats have no encoder here at all.** RAR, HE-AAC, xHE-AAC and bit-exact AVIF lossless are cited or absent, never estimated. Hardware video encoders (NVENC, QSV, AMF) and any 4K source are also untested.
