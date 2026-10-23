# TradeShift: short report

## 1. Question

When the US put tariffs on a supplier, did its imports move to other countries (trade
diversion), or did they shrink (trade destruction)? TradeShift answers this product by
product (HS6), for ten US tariff actions between 2016 and 2019, and explains every
shift in one sentence.

## 2. Data

| Source | What | Coverage |
|---|---|---|
| US Census international trade API | US general imports by country of origin and HS6, monthly | Jan 2015 – Aug 2026, 140 months |
| UN Comtrade | Japan's imports by partner (second importer); US net weights (quantity check); Singapore's exports to the US | Japan 2015–2026; US weights 2017–2020; Singapore 2015–2026 |
| SingStat | Singapore's official re-exports and domestic exports to the US; S$/US$ rate | 2015–2026 |
| Federal Register | Tariff events: dates, tariffed and exempt countries, covered products | 10 events, 2016–2019 |

Checks: the sum of our country rows equals the Census all-countries total in **every one of
the 140 months (0.0% difference)**. The Section 301 product lists parsed from the USTR
annexes match the official counts within 0.3%.

We keep the top 15 suppliers per product (the rest as "rest of world"), which leaves
11.2 million monthly rows.

## 3. Method (summary; details in the code and `docs/design_choices.md`)

- **Share** of supplier *j* in product *k*: imports from *j* / total imports of *k*, pooled over
  12 months before vs 12 months after each tariff (skipping 2 months for goods in transit).
- **Detector:** a tariffed supplier loses ≥ 5 points, an untariffed supplier gains ≥ 3 points,
  and the product has ≥ US$10m of annual imports. **Higher confidence** when net-weight shares
  move the same way. **Value redirected** = min(loss, gain) × average annual imports.
- **Trade destruction:** total imports fall ≥ 25%.
- **HHI** = Σ(100 × share)², before and after each event.
- **Difference-in-differences** per event: tariffed vs untariffed HS6 products in the same HS4
  headings, product and month fixed effects, standard errors clustered by product.
- **Singapore:** re-exports by product estimated as Singapore's exports to the US minus US
  imports of Singapore-origin goods.

## 4. Results

### Flags by event

| Event | Flags | Higher confidence | Value redirected (US$bn a year) |
|---|---|---|---|
| Section 301 List 1 | 123 | 77 | 8.3 |
| Section 301 List 2 | 54 | 43 | 2.9 |
| Section 301 List 3 | 457 | 385 | 15.8 |
| Section 301 List 4A | 279 | 181 | 17.2 |
| Section 232 steel (first wave) | 46 | 38 | 1.2 |
| Section 232 steel (EU, Canada, Mexico) | 66 | 58 | 0.8 |
| Section 232 aluminium (first wave) | 9 | 9 | 0.5 |
| Section 232 aluminium (EU, Canada, Mexico) | 9 | 8 | 0.2 |
| Anti-dumping: washers from China | 1 | 0 | 0.6 |
| Section 201 washers | 0 (trade destruction, see below) | – | – |

In all 913 Section 301 flags China is the supplier that lost share. **Vietnam is the most
frequent gainer (100 products)**, followed by Mexico (91), Canada (83), India (71) and Taiwan (53).

### Top shifts

| Product | Event | Lost share | Gained share | Redirected (US$m/yr) | Total imports | Confidence |
|---|---|---|---|---|---|---|
| 8473.30 computer parts & accessories | List 3 | China 69.5% → 30.2% | Taiwan 6.1% → 23.3% | 3,939 | −24.4% | value only |
| 8517.62 voice/data transmission machines | List 4A | China 47.2% → 32.3% | Vietnam 5.8% → 12.1% | 2,474 | −6.1% | higher |
| 8523.51 solid-state storage | List 4A | China 31.7% → 4.5% | South Korea 10.3% → 30.9% | 2,395 | +26.3% | value only |
| 8471.50 digital processing units | List 3 | China 19.0% → 5.3% | Taiwan 1.3% → 8.9% | 2,284 | +4.4% | higher |
| 8528.72 colour TV receivers | List 4A | China 35.8% → 17.4% | Mexico 61.3% → 74.6% | 1,799 | −8.8% | higher |
| 8471.70 computer storage units | List 1 | China 19.1% → 5.2% | Thailand 42.2% → 58.0% | 1,185 | −29.3% | higher |
| 8541.40 photosensitive semiconductors (solar) | List 2 | China 16.6% → 4.4% | Malaysia 20.8% → 33.6% | 871 | −9.5% | value only |
| 8450.20 washing machines > 10 kg | AD washers | China 75.1% → 1.7% | Vietnam 0.0% → 41.5% | 565 | −8.2% | value only |
| 9401.61 upholstered wooden seats | List 3 | China 67.5% → 56.3% | Vietnam 13.0% → 21.8% | 516 | −1.3% | higher |

### Validation: difference-in-differences

| Event | β (points) | s.e. | t | Treated | Controls |
|---|---|---|---|---|---|
| Section 301 List 1 | −3.0 | 0.8 | −3.9 | 518 | 46 |
| Section 301 List 2 | −6.6 | 1.2 | −5.6 | 188 | 9 |
| Section 301 List 3 | −4.2 | 0.8 | −5.6 | 1,915 | 148 |
| Section 301 List 4A | −2.7 | 0.7 | −4.1 | 1,053 | 100 |
| Section 232 steel | −7.1 | 3.3 | −2.1 | 135 | 4 |
| Section 232 aluminium | −6.1 | 4.0 | −1.5 | 20 | 2 |
| Section 232 steel / aluminium extensions | +3.4 / +0.2 | 3.4 / 4.7 | – | 135 / 20 | 4 / 2 |

For every Section 301 list, China's share fell 3–7 points more in tariffed products than in
untariffed products of the same headings, with large t-statistics. The Section 232 checks have
very few untariffed controls (steel and aluminium headings are almost fully covered), so we
don't rely on them. The extensions to the EU, Canada and Mexico show no effect; their duties
on Canada and Mexico were lifted inside the after window.

### The washing-machine case

- **2016 → 2017 (anti-dumping duties on China, July 2016):** China's share of US imports of
  large washers (HS 8450.20) fell from **75.1% to 1.7%**, while Vietnam went from 0% to 41.5% and
  Thailand from 1.1% to 23.6%. Total imports barely changed (−8%): this is diversion.
- **2018 (Section 201 safeguard on all suppliers):** no untariffed supplier could gain, so the
  detector rightly flags nothing; instead total imports of HS 8450.20 fell **32%**
  (US$1,639m → US$1,111m) as production moved to new US plants. That is trade destruction, which
  the detector page lists separately.

This matches the published account of the case (Flaaen, Hortaçsu and Tintelnot, *American
Economic Review*, 2020).

### Singapore lens

229 of 3,888 Section 301 products show estimated Singapore re-exports to the US up 25% or more
after the first list that covered them. The estimate follows SingStat's official total year by
year but is about 25–35% higher in level, probably because of valuation (FOB vs customs value),
timing, and reporting differences between the two countries' records. Read it as a trend in
Singapore's hub role, not an exact amount, and never as evidence of transshipment.

## 5. Limitations

- Shifts in share are not proof that the tariff caused them; the DiD check is a validation per
  list, not a claim about each product.
- No prices or costs, so no claims about tariff incidence or comparative advantage.
- Quantities exist only for 2017–2020 (Comtrade net weights), so the 2016 washer event and some
  flags are "value only".
- Lists overlap within some HS6 codes (part on List 1, part on List 3); the app shows each
  product's largest shift once.
- The List 4A after window runs into the 2020 COVID shock.
- HS revisions (2017, 2022): affected codes are flagged and left out of the DiD.

## 6. Cloud deployment

One CloudFormation stack builds the VPC, security groups, S3, RDS, the batch server, the
load-balanced Auto Scaling Group and the monitoring in about 20 minutes, with no manual steps
after Submit. The cloud tests (load balancing, failover, scale-out and scale-in, security,
rebuild) are in `docs/testing.md`.
