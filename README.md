# Dunkin' Massachusetts: Fastest Route Recreation
Practice project recreating DataDork's "fastest route to every Dunkin'
in Massachusetts" using open data and a real road network. Practice
only, concept from DataDork.

## Dataset definition
- Definition: Include regular Dunkin's stores, Dunkin's under shared
  roofs, and gas-station Dunkin's.
- One stop per road-reachable destination: multiple counters behind a
  single destination (airport, ballpark, arena) count as one stop.
- Membership is defined by Dunkin's own location directory. Overture
  and OSM serve as coordinate sources and cross-checks, not as
  membership evidence on their own.
- Primary pull: Overture Maps places, release 2026-09-23.1,
  pulled 10/18/2026 (1,364 raw rows).
- Referee and membership source: Dunkin's location directory,
  scraped 10/18/2026 (297 town pages, 1,035 listings).
- Cross-check source: OpenStreetMap via the Overpass API, pulled
  10/18/2026 (758 rows). OSM is volunteer-mapped and undercounts;
  counters inside other businesses are under-mapped.
- True count is hard to pin down. Sources disagree because
  definitions and snapshot dates differ: the reference video used
  1,028, the officical Dunkin' directory lists 1,035, Google shows ~1,040. Cleaning
  rules will not be adjusted to hit another source's number.
- Known limit: the directory is a live snapshot from 10/18/2026
  while Overture's release is dated 2026-09-23.1; a small number of
  disagreements are snapshot drift, not errors.
- Final dataset: 1,019 stops, every stop with coordinates that
  survived a full audit (dunkins_final_v8.csv).

## Reference (DataDork's video)
- 1,028 stops, 2,308 miles, 2 days 17 hours, loop starting and
  ending in Quincy. His constants: $3.79 per coffee, gas $407
  (implies 25 MPG at $4.41/gal).
- This project uses my own constants instead: iced coffee at $3.84, and
  diesel at $6.29/gal for my 2011 Jetta TDI at an estimated
  35 MPG. At the final totals that is $3,912.96 of coffee and
  67.3 gallons of diesel for $423.57.
- Distances are true road distances throughout (OSRM), not
  straight-line.
- Settled route: 1,019 stops, 2,356.9 miles, 86.1 driving hours
  (3 days 14 hours). Best route the solver found, not provably
  optimal; a 30-minute re-solve returned identical numbers, so
  the route is final.
- Finished video: dunkin_tour_final.mp4, 64 seconds at
  1920x1080, the settled loop under the live dashboard with
  the "Roadrunner" soundtrack. Concept to finished product
  in just under 24 hours.

## Repository layout
- python/01_pull: the three source pulls (OSM, Overture,
  directory scrape).
- python/02_clean: the cleaning stages and geocoding passes.
- python/03_validate: the duplicate pass, the coordinate audit,
  and the pin repairs.
- python/04_route: the matrix build, the solver, and the route
  map.
- python/05_video: the basemap and the dashboard/renderer.
- data/raw: the pulls as downloaded, untouched; basemap/ inside
  it holds the Census downloads and extractions.
- data/clean: the working set the later stages read (final
  dataset, matrices, route files, basemap data).
- data/clean/history: the archived cleaning lineage (stage
  outputs, dataset versions v1-v7) and the audit worksheets,
  kept as the provenance record.
- osm.pbf/: the Geofabrik extract and the OSRM preprocessing
  outputs (contents gitignored; rebuild with the commands in
  the OSRM setup log entry).

## How the data was pulled
- Four nets via OSM: name, brand, operator (case-insensitive
  "Dunkin"), plus brand:wikidata = Q847743 for stores with no
  Dunkin' words.
- dunkins_raw_v1.csv: first cast, three nets only, 757 rows.
- dunkins_raw_v2.csv: second cast, four nets (added Q847743), 758 rows.
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
  priority signal, not a removal reason; a
  permanently-closed flag is a queue flag, not a removal.
- 10/18/2026: Logan Airport: the directory lists 13 airport
  listings (10 distinct locations, some double-listed on the
  Boston and East Boston pages, typos included). Under the
  one-stop-per-destination rule Logan counts as a single stop;
  exactly one Logan row survives.
- 10/18/2026: Fenway Park: the directory lists two stores at
  4 Jersey Street, Boston. Same rule as Logan: one stop.
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
  alone don't justify a removal; the directory's per-town address
  lists are now the official authority.
- 10/18/2026: Membership frame flipped once the directory was
  scraped in full: the Dunkin' directory defines the dataset, and
  Overture rows matching no official listing are discarded as a
  class (no individual rulings). Overture's remaining role is
  coordinate donor. This retired a 312-row manual review queue that the
  earlier frame would have required.
- 10/18/2026: Pin provenance hierarchy for directory-only
  stores: exact Overture match, then fuzzy donor from a discarded
  Overture row, then Nominatim address geocode, then Nominatim
  POI (name) search. POI-placed pins are flagged for a visual
  check at validation.
- 10/18/2026: Duplicate rulings. Two pairs collapsed to one stop
  each: 80 Main St, Carver (one store, two listings) and
  1 Horizon Way, Everett (Encore Casino). Every other close pair was verified
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
  batch geocoder; Nominatim as fallback). A disagreement is just a
  flag: a pin is replaced only when two
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
- 10/18/2026: Video backdrop sourcing. The map under the route is
  Census TIGER data: town boundaries plus roads classified into
  tiers by MTFCC code (limited-access, primary/secondary, local,
  service), drawn level-of-detail style so finer streets appear
  as the camera zooms in, the way a commercial map behaves. The
  route itself remains OSRM/OSM geometry; only the wallpaper
  changed source. Town lines were chosen over the reference
  video's county lines.
- 10/18/2026: The land is filled soft green (#6FC276) from the
  town polygons and water stays paper-colored, with no separate
  water layer. Town boundaries come from the Census cartographic
  file, which clips towns to the real shoreline; the
  legal-boundary file was tried first and rejected because town
  jurisdictions extend into the bays and painted the water
  green. The cartographic file initially slipped the island
  towns back in past the county filter; they are excluded by
  town name, so the backdrop follows the same no-islands
  definition as the dataset.
- 10/18/2026: Local roads (tier 3) enter the backdrop at window
  widths under 0.6 degrees of longitude. A 0.3-degree threshold
  was tried and rejected: at metro and rural widths the map went
  too sparse to read.
- 10/18/2026: Dashboard and pacing design. The map is the
  full-frame background and the dashboard is a band across the
  top, following the reference video's layout: miles gauge on
  the left (fills light green to deep green, number and
  MILES DRIVEN label beneath), the header, the stops fraction,
  a HEADED TO town and address, and the metric rows (day
  counter, hours, iced coffee dollars, gas dollars and
  gallons). The day counter counts driving days (hours / 24,
  rounded up). The animation runs about a minute of motion at
  30 fps with 2 seconds of stillness at the head and tail; the
  marker's speed is proportional to each leg's real OSRM drive
  time, and the camera window scales with the distance to the
  next stop, smoothed, opening and closing on the full-state
  view. Type is set in free chunky stand-ins (Titan One,
  Archivo Black) rather than Dunkin's proprietary face.
- 10/19/2026: Camera zoom, settled in the render test loop.
  The first design scaled the window with the distance to the
  next stop (gain 2.6, floor 0.055 degrees); two test renders
  were rejected as unwatchable, too zoomed in with the marker
  constantly leaving the frame (smoothing lag, and a frame
  much shorter than it is wide, were accomplices). The final
  rule is region scale: gain 10, floor 0.65 degrees (about
  33 miles), smoothing 0.08 per frame. The view always shows
  which part of the state you are in and the marker travels
  inside it. Side effect: windows above 0.6 degrees skip the
  local-streets tier, which cut the full render to about
  20 minutes for 1,920 frames.
- 10/19/2026: Pacing kept frantic at 60 seconds of motion by
  choice. Slower cuts (75 / 90 s) were considered and
  declined; the worst case of the choice is a re-render.
- 10/19/2026: Soundtrack: "Roadrunner" by The Modern Lovers
  (Natick). Trimmed to the video's 64 seconds length and muxed in with ffmpeg.

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
  the Dunkin' directory's per-town counts. Working set 1,287 stores vs an
  adjusted target of about 1,025 (directory 1,035, minus the
  Logan and Fenway collapses). 136 towns reconciled exactly, 124
  over, 5 under by one store each: Devens, Holbrook, Northbridge,
  Tewksbury, Tyngsboro (patch candidates).
- Directory scrape (webscrape.py): 1,035 official listings
  captured and count-verified per town. The directory has its
  own mess: Marlboro (3) and Marlborough (2) are separate pages
  with disjoint stores, 6 listings are exact duplicates, and
  some Logan Airport stores are double-listed across town pages.
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
- OSRM setup: Docker, osrm/osrm-backend v5.26.0. Preprocessing
  (extract with the car profile, partition, customize; MLD) run
  on massachusetts-261017.osm.pbf; routed serves the result with
  --max-table-size 5000.
- Distance matrix (build_matrix.py): one table call produced
  the full 1,019 x 1,019 distance and duration matrices.
  Unreachable pairs: zero, which also closes the last pin
  question (a stop plotted somewhere unroutable would have
  surfaced here). Longest single leg in the state: 400 km.
- First solve (solve_route.py): OR-Tools, PATH_CHEAPEST_ARC
  start, GUIDED_LOCAL_SEARCH improvement, 600 s box, road
  distance as the objective, anchored at 543 Southern Artery,
  Quincy (the original store). Result: 1,019 stops,
  2,356.9 miles, 86.1 driving hours, against DataDork's
  2,308 miles / 65 hours / 1,028 stops. Distance lands within
  2.1% on a first pass; the time gap is profile speeds plus
  optimizing distance rather than duration (the tour averages
  27.4 mph; his implies 35.5 mph).
- Route map (plot_route_map.py): road geometry fetched for all
  1,019 legs from the local server, zero failures, 175,377 path
  points stitched into route_geometry.geojson and rendered as
  route_map.png. The map doubles as the validation plot: the
  tour traces the state cleanly and no pin sits anywhere a
  store could not be.
- Second solve: the solver box was tripled to 1,800 s and the
  result came back identical (2,356.9 miles, 86.1 hours).
  Guided local search had already converged inside the first
  run. The route is settled as the best found, not provably optimal.
- Basemap (base_map.py): Census TIGER downloads (cartographic
  town boundaries; road files for the 12 mainland counties)
  converted to tiered segment arrays (basemap_roads.npz,
  basemap_towns.npz). Four test frames (state, metro, dense
  Quincy, rural Berkshires) iterated on the design calls in the
  decision log and approved: green land, town lines, level-of-
  detail roads, islands absent.
- Dashboard (dashboard.py): the full HUD and camera system over
  the basemap, driven by the route timeline. Three stills
  (opening, a Boston frame at the City Hall Plaza arrival, and
  the final frame) iterated on spacing until most overlapping
  and clipping was gone: the final still reads 2,356.9 miles driven, stops
  1019 / 1,019, Day 4 at 86.1 hours, iced coffee $3,912.96, gas
  $423.57 and 67.3 gallons. Approved as the render design.
- Reorganization: the scripts were grouped into phase
  subfolders under python/ (01_pull through 05_video) with
  their ROOT path lines adjusted one level to match, and the
  cleaning lineage and audit worksheets were archived under
  data/clean/history/. Verified by the basemap running clean
  from its new home in 05_video.
- Renders: four 10-second opening tests iterated the camera
  (street scale rejected twice as too zoomed in; region scale
  with faster smoothing tracked the pointer; one further zoom
  notch, gain 10 with a 0.65-degree floor, was the sweet
  spot). The full render drew 1,920 frames in about
  20 minutes: 2 s state-view hold, 60 s of motion, 2 s
  settle, out to dunkin_tour.mp4.
- Soundtrack and finish: "Roadrunner" (The Modern Lovers)
  fetched with yt-dlp, trimmed in Ableton to exactly 64 s
  (second attempt; Ableton's auto-warp had to be switched
  off), and muxed with ffmpeg into dunkin_tour_final.mp4.
  Project complete.

## Pipeline
1. Pull locations to CSV [x] (Overture, OSM, official directory)
2. Clean and reconcile [x] (1,019 stops, all pinned)
3. Validation [x] (coordinate audit; per-town counts reconcile
   once village and neighborhood filing labels are folded; map
   plot is the route map)
4. OSRM road engine [x] (preprocessing done, routed serving)
5. Distance matrix [x] (1,019 x 1,019, zero unreachable pairs)
6. Route solve [x] settled: 2,356.9 miles, 86.1 hours; the
   30-minute pass confirmed the 10-minute result
7. Basemap [x] (tiered TIGER roads and town lines, LOD test
   frames approved)
8. Dashboard [x] (HUD and camera approved on still frames)
9. Video render [x] (four 10-second opening test renders
   iterated the camera; full render 1,920 frames at 1920x1080,
   30 fps, soundtrack muxed in)
