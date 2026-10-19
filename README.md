# Dunkin' Massachusetts: Fastest Route Recreation
Practice project recreating DataDork's "fastest route to every Dunkin'
in Massachusetts" using open data and a real road network. Practice
only; the concept is DataDork's, so this will not be portfolio'd.

## Dataset definition
- Definition: Include regular Dunkin's stores, Dunkin's under shared
  roofs, and gas-station Dunkin's. Mainland, road-reachable locations
  only; the islands are excluded by definition.
- One stop per road-reachable destination: multiple counters behind a
  single destination (airport, ballpark, arena) count as one stop.
- Membership is defined by Dunkin's own location directory. Overture
  and OSM serve as coordinate sources and cross-checks, never as
  membership evidence on their own.
- Primary pull: Overture Maps places, release 2026-09-23.1,
  pulled 10/18/2026 (1,364 raw rows).
- Referee and membership source: Dunkin's location directory,
  scraped 10/18/2026 (297 town pages, 1,035 listings).
- Cross-check source: OpenStreetMap via the Overpass API, pulled
  10/18/2026 (758 rows). OSM is volunteer-mapped and undercounts;
  counters inside other businesses are under-mapped.
- There is no single true count. Sources disagree because
  definitions and snapshot dates differ: the reference video used
  1,028, the directory lists 1,035, Google shows ~1,040. Cleaning
  rules are never adjusted to hit another source's number.
- Known limit: the directory is a live snapshot from 10/18/2026
  while Overture's release is dated 2026-09-23.1; a small number of
  disagreements are snapshot drift, not errors.
- Final dataset: 1,019 stops, every stop with coordinates that
  survived a full audit (dunkins_final_v8.csv).

## Reference (DataDork's video)
- 1,028 stops, 2,308 miles, 2 days 17 hours, loop starting and
  ending in Quincy. His constants: $3.79 per coffee, gas $407
  (implies 25 MPG at $4.41/gal).
- This project uses my own constants instead: my coffee order's
  price, my gas station's price, my car's MPG.
- Distances are true road distances throughout (OSRM), never
  straight-line.

## How the data was pulled
- Four nets via OSM: name, brand, operator (case-insensitive
  "Dunkin"), plus brand:wikidata = Q847743 for stores with no
  Dunkin' words.
- dunkins_raw_v1.csv: first cast, three nets only, 757 rows.
- dunkins_raw_v2.csv: second cast, four nets, 758 rows.
- Overture via DuckDB against the release's GeoParquet on S3:
  Massachusetts bounding-box prefilter, addresses region = 'MA',
  three nets (names.primary, brand names.primary, brand wikidata
  Q847743). Returned 1,364 rows to overture_dunkins_raw.csv.
- Directory via webscrape.py (Playwright): the town pages load
  their location cards with JavaScript, so a plain HTTP fetch
  returns an empty shell. The scraper renders each of the 297
  town pages and reads the cards. Per-town counts printed by the
  directory itself audit the scrape; all 297 towns agreed, final
  file official_addresses.csv holds exactly 1,035 rows (street
  address + town per listing; the cards print no ZIP).

## Decision log
- 10/18/2026: Reran the OSM call with a fourth net (brand:wikidata
  Q847743) to catch stores with no Dunkin' words. Gain: 1 row
  (757 to 758). OSM's four nets are complete against OSM itself;
  the gap to ~1,040 is OSM coverage, so OSM was demoted to a
  cross-check layer.
- 10/18/2026: Adopted Overture as the primary pull: 1,364 raw
  rows is a workable superset to clean down.
- 10/18/2026: Profiled the Overture pull before writing rules:
  152 rows under 0.9 confidence, 13 rows with null addresses, one
  bare address "1775" (Hanover), 34 extra rows sharing a street
  address + town. Duplicate rule: same normalized address and
  town AND within 100 m is a safe automatic merge; anything else
  suspicious goes to manual review. Low confidence is a review
  priority signal only, never a removal reason; a
  permanently-closed flag is a queue flag, not a removal.
- 10/18/2026: Logan Airport: the directory lists 13 airport
  listings (10 distinct locations, some double-listed on the
  Boston and East Boston pages, typos included). Under the
  one-stop-per-destination rule Logan counts as a single stop;
  exactly one Logan row survives.
- 10/18/2026: Fenway Park: the directory lists two stores at
  4 Jersey Street, Boston. Same rule: one stop.
- 10/18/2026: TD Garden: the directory lists the arena four
  times under variant labels (100 Legends Way North Station;
  One Legends Way Fleet Center; One Fleet Center Fleet Center;
  Causeway Street Fleet Center). One destination, one stop; the
  single Overture row at 1 Legends Way is the stop.
- 10/18/2026: Taunton, 185 Weir St: no Dunkin' there per the
  official site; the real store is 491 Weir St, already in the
  data. Both 185 Weir records (a wrong-address phantom and a
  Honey Dew Donuts carrying a Dunkin' brand field) are false.
- 10/18/2026: Supplement rule: a real store missing from Overture
  gets added as a patch row sourced from the official directory,
  documented as such.
- 10/18/2026: Disputed addresses are refereed against Dunkin's
  own location directory. The site's location SEARCH proved buggy
  by omission (real stores failed to surface), so search results
  alone never justify a removal; the directory's per-town address
  lists are the authority.
- 10/18/2026: Membership frame flipped once the directory was
  scraped in full: the directory defines the dataset, and
  Overture rows matching no official listing are discarded as a
  class (no individual rulings). Overture's remaining role is
  coordinate donor. This retired a 312-row manual queue that the
  earlier frame would have required.
- 10/18/2026: Pin provenance hierarchy for directory-only
  stores: exact Overture match, then fuzzy donor from a discarded
  Overture row, then Nominatim address geocode, then Nominatim
  POI (name) search. POI-placed pins are flagged for a visual
  check at validation.
- 10/18/2026: Duplicate rulings. Two pairs collapsed to one stop
  each: 80 Main St, Carver (one store, two listings) and
  1 Horizon Way, Everett. Every other close pair was verified
  against the directory and Google Maps and ruled TWO stops,
  including several pairs of stores directly across the street
  from each other (2345/2368 GAR Hwy, Swansea; Newbury St,
  Peabody), the two Route 24 service pavilions in Bridgewater
  (separate plazas on opposite highway sides, so the route
  visits each on its own side), the two Northeastern University
  listings, and the two Beth Israel listings (separate
  buildings).
- 10/18/2026: Coordinate audit standard. Every pin was
  cross-examined against an independent geocoder (US Census
  batch geocoder; Nominatim as fallback). A disagreement is a
  flag, not a verdict: a pin is replaced only when two
  independent geocoders agree with each other against it (or a
  single witness at extreme distance), and the replacement must
  pass a town-centroid gate. Pins that no address geocoder can
  check (service pavilions, venue listings) are hand-placed from
  Google Maps.
- 10/18/2026: 1 Horizon Way, Everett: the collapse kept the
  locked-keep record, but that record's pin sat ~2 km east,
  toward the harbor. The dropped twin's pin and a fresh geocode
  agreed with each other at the casino's actual location; the
  final pin is hand-placed there.

## Cleaning log
- Stage 1 (dataclean.py): 1,364 raw rows in. 7 non-stores removed
  automatically (distribution centers, Canton HQ, charitable
  trust, university, a pet service, an out-of-state ghost). 14
  duplicate rows merged automatically under the 100 m rule.
  1,343 rows out, plus a 100-row manual review queue. (The stage-1
  file carries all 1,364 rows with a disposition column; later
  scripts filter on it.)
- Manual queue: worked in Excel against the location search and
  stopped by choice at 82 decisions: 26 keeps (locked; each
  matched the official site 1 for 1) and 56 tosses (provisional,
  because the search's bugginess was omission). The 18 unreviewed
  rows returned to the pool untouched.
- Stage 2 (dataclean2.py): town-by-town reconciliation against
  the directory's per-town counts. Working set 1,287 stores vs an
  adjusted target of about 1,025 (directory 1,035, minus the
  Logan and Fenway collapses). 136 towns reconciled exactly, 124
  over, 5 under by one store each: Devens, Holbrook, Northbridge,
  Tewksbury, Tyngsboro (patch candidates).
- Directory scrape (webscrape.py): 1,035 official listings
  captured and count-verified per town. The directory has its
  own mess: Marlboro (3) and Marlborough (2) are separate pages
  with disjoint stores, 6 listings are exact duplicates, and
  some Logan stores are double-listed across town pages.
- Stage 3 (dataclean3.py): full reconciliation join. Both sides
  run through one shared address key (directionals expanded,
  Mass Ave alias, keys cut after the street suffix so venue and
  plaza tails cannot break matches). Logan, Fenway, and TD Garden
  consumed by rule first. Results: 964 verified matches, 2
  provisional tosses resurrected by unmet official demand
  (including 550 Huntington Ave, Boston), 50 directory-only
  addresses became patch rows, and 312 working rows matched
  nothing official and were discarded as a class under the
  membership rule. First run needed two fixes: filter the
  stage-1 disposition flags (21 auto-action rows had re-entered
  the pool) and collapse Logan to a single surviving row.
- Stage 4 (dataclean4.py): pin donation for the 50 patches. 13
  pins donated by fuzzy match from the discarded Overture rows;
  no patch turned out to duplicate a locked keep; 37 addresses
  went to the geocode queue. Stop count held at 1,022.
- Geocoding (geocode.py, Nominatim): 20 of 37 addresses placed,
  including 140 Nauset St, New Bedford (a store the manual queue
  had identified by its correct address) and the Devens and
  Holbrook under-town patches. 1,005 of 1,022 stops pinned.
- Fix pass (geocode2.py): deleted one patch that was a Logan
  listing in disguise (the directory's own typo, "Logal
  International Airport", had slipped the Logan filter), taking
  the stop count to 1,021. Repaired aliases ("g a r" spaced,
  "mac arthur" split) recovered donor pins for both Swansea GAR
  Hwy listings and 568 MacArthur Blvd, Bourne at similarity
  1.00. Cleaned queries placed 8 more, including both
  Northeastern University addresses, both Tewksbury patches, and
  the Whitinsville (Northbridge) patch. 1,016 of 1,021 pinned.
- Final pass (geocode3.py): the last 5 placed. Lynnfield's
  8 Broadway and Worcester's 177 Southwest Cutoff via cleaned
  street queries; the Route 24 Bridgewater service pavilion,
  Tyngsboro's 95 Westford Rd, and Webster's 138 East Main St via
  POI name search (flagged for the validation eyeball).
- Interim dataset: 1,021 stops, 1,021 with coordinates
  (dunkins_final_v5.csv). All five under-towns from stage 2 are
  represented.
- Duplicate pass (validate_duplicates.py): same-address keys,
  proximity within 150 m, directional and venue signals produced
  56 unique suspect pairs. Ruled per the decision log: 2
  collapses, everything else confirmed as two distinct stores.
  Stop count 1,021 -> 1,019. Five ruled pairs had corrupt pins
  (real stores plotted on top of each other) and went to the
  coordinate audit as known-bad.
- Full coordinate audit (validate_full.py): collapses applied,
  then every pin cross-examined against the US Census batch
  geocoder (705 Exact and 221 Non_Exact matches; 72 Nominatim
  fallbacks for Census misses). Results: 843 pins agree within
  150 m, 94 minor disagreements (150-500 m, logged), 56
  suspects, 19 rows no address geocoder can check, and all 5
  known-bad pairs repaired on the evidence: 152 Center St,
  Pembroke's pin was 19,080 m off (plotted on the Holbrook
  store); 1 South Station's donor pin 3,113 m off; 1001 South
  St, Wrentham 836 m off (the shared pin belonged to the
  outlets store; its pin was vindicated); 440 Middlesex Rd,
  Tyngsboro 503 m off; 30 Union St, Holbrook 108 m off. 757
  Centre St, Boston was vindicated in the same pass.
- Suspect repair (repin_suspects.py): under the two-witness
  rule, 31 suspect pins were convicted and replaced (stamped
  repin_two_witness or repin_single_witness; median move
  2.1 km, largest 49.8 km at 12 Washington St, Chelsea, a
  single-witness Census replacement later spot-checked by hand
  at ~100-150 ft from the store). A centroid gate refused one
  swap at 160 South St, Plymouth, where the fresh pin was
  itself 37 km out of town.
- Hand pins (apply_hand_pins.py): the 24 suspects where the two
  geocoders disagreed with each other, plus 1 Horizon Way and
  the two Route 24 pavilions, were hand-placed from Google Maps
  on the actual stores (27 hand pins total). Eyeball outcome:
  most of the 24 old pins were vindicated, landing within ~30 m
  of the hand placements; in that class the witnesses were the
  noise. 160 South St, Plymouth's original pin proved accurate
  to 5 m: Census had no match for it and the Nominatim fallback
  had pointed at a same-named street in another town, which
  manufactured its suspect flag.
- Final dataset: 1,019 stops, 1,019 with coordinates, zero
  duplicate coordinate pairs (dunkins_final_v8.csv). Pin
  provenance: 912 Overture, 36 audit repins, 29 Nominatim fills,
  15 fuzzy donors, 27 hand-placed. Residual documented class:
  19 rows no address geocoder can check (venue and plaza
  listings); all 19 pins sit inside their own towns.

## Pipeline
1. Pull locations to CSV [x] (Overture, OSM, official directory)
2. Clean and reconcile [x] (1,019 stops, all pinned)
3. Validation (coordinate audit [x]; per-town counts and map
   plot still open)
4. OSRM road engine (setup done: Docker, osrm image, MA .osm.pbf
   downloaded; extract/partition/customize pending)
5. Distance matrix [ ]
6. Route solve (loop from Quincy) [ ]
7. Dashboard + video render (small test render before the full
   render) [ ]
