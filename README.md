# Codec-summary-mayk

Evaluating the best codec / compression / algorithm / file type for each use case, including a dashboard visualization of the trade-offs and the optimum choice for each user region.

Images are done. Audio, video, archives, datasets and columnar storage are still to come.

## Images

**[docs/image_codec_tradeoff_map.html](docs/image_codec_tradeoff_map.html)** is a self-contained page: a decision map with seven labelled regions, plus the measured rate-distortion data behind it. Open the file directly, no build or server needed.

The two axes that decide everything:

- **How much continuous tone the image carries**, from flat UI graphics through ordinary photography to 10-bit HDR.
- **How far you are willing to walk away from universal decoding** in exchange for smaller files.

### What the measurements say

Every number on the page was produced by the scripts in `scripts/`, not quoted from elsewhere. 14 pristine Kodak reference photographs across a quality ladder in five codecs, plus one rendered 1440x900 application screenshot. Quality scored with SSIMULACRA2, so codecs are compared at matched perceptual quality rather than at matched slider numbers, which are meaningless across encoders.

| Finding | Detail |
|---|---|
| AVIF and JPEG XL swap places at SSIMULACRA2 87 | Below that AVIF is the smaller file (31.5% under JPEG at delivery quality, 38.1% at thumbnail quality). Above it JPEG XL is (30.7% at visually lossless, where AVIF is down to 17.5%). |
| WebP is a modest win on photographs | Only 14.6% under baseline libjpeg-turbo at delivery quality, and a modern JPEG encoder claws most of that back. |
| WebP lossless is the screenshot answer | 67.7% under optimised PNG on the test UI, pixel-identical. It also beats JXL lossless (87% larger) and every lossy option at the same size. |
| No lossy codec handles text well | AVIF stalls at SSIMULACRA2 84 on the screenshot even at q100; WebP stalls at 82. Lossy WebP q80 was larger than lossless WebP and scored 77. |
| Lossy PNG is real but no longer optimal | Palette quantisation took the screenshot from 85.602 to 33.336 bytes at a score of 93. WebP lossless got to 27.646 bytes with nothing lost. |
| The JPEG quality knee is q75 to q85 | One SSIMULACRA2 point costs 0.057 bpp at q75, 0.114 at q85 and 0.611 by q98. |
| On photographs the lossless order flips | JPEG XL lossless is 37.0% under PNG, WebP lossless 29.5%. Flat graphics and photographs want different lossless coders. |

The JPEG figures come from stock libjpeg-turbo, so they are the pessimistic case: mozjpeg and jpegli both do considerably better while still emitting a plain JPEG.

## Reproducing

Needs Python 3.11+ and a working network for the test corpus.

```bash
pip install pillow pillow-heif pillow-avif-plugin pillow-jxl-plugin ssimulacra2

python3 scripts/fetch_testdata.py                            # Kodak reference photos
python3 scripts/measure_photo_rd.py testdata/photos/*.png    # main quality ladder
python3 scripts/measure_photo_tail.py testdata/photos/*.png  # extends the high-quality end
python3 scripts/measure_synthetic.py                         # renders and measures the UI screenshot
python3 scripts/measure_extra.py                             # lossless, palette, and the tails
python3 scripts/analyse.py                                   # matched-quality interpolation
python3 scripts/make_prose.py                                # derives every sentence containing a number
python3 scripts/build_page.py scripts/page_template.html docs/image_codec_tradeoff_map.html
```

The full sweep takes roughly 45 minutes. Raw results are committed under `data/` so the page can be rebuilt without re-running any of it.

### Layout

| Path | Contents |
|---|---|
| `docs/` | The built page. Self-contained: fonts and data are inlined, nothing is fetched at runtime. |
| `scripts/` | Measurement, analysis and build. `page_template.html` is the page source before font and data injection. |
| `data/` | Raw sweep results and the derived analysis, as JSON. |
| `assets/fonts/` | Tektur, Instrument Sans and Geist Mono, all SIL Open Font License (texts included). |
| `testdata/` | Reference photographs, fetched rather than committed. |

### Caveats

- Reference photographs are 768x512. Modern camera output is 20 to 50 times larger, and the newer codecs generally do relatively better at higher resolution, so their lead is if anything understated here.
- The flat-graphics conclusions rest on a single rendered UI. The effect sizes are large enough that the direction is safe; the exact percentages are not general constants.
- AVIF lossless is absent. The Python binding used here cannot produce bit-exact AVIF, since its lossless flag still round-trips through a lossy colour conversion.
