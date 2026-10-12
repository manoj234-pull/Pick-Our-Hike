# Data and assets

## Purpose

Pick Our Hike uses ten fictional trails to demonstrate group planning. Trail names,
distances, ascent, dog rules, opening hours, weather and drive times are invented.
They do not describe real destinations and must not be used for navigation or
real travel decisions. Any resemblance to an actual trail name is incidental.

Redlands City Hall is a real place name used as the fixed starting label. The
invented driving values are not measured journeys from that location.

## Included files

| File | Contents |
|---|---|
| [route-facts.json](data/demo/route-facts.json) | Fictional route names, loop distances, uphill gain, dog rules and opening hours |
| [offline_trip_context_2026-10-11.json](data/demo/offline_trip_context_2026-10-11.json) | Invented weather, outbound/return driving allowances and arrival labels |
| [trail_scene.svg](assets/trail_scene.svg) | Original conceptual trail illustration; not a map or a specific destination |
| [pick_our_hike.css](assets/pick_our_hike.css) | Local interface styling |

Both JSON files are required by the app. The date in the context filename labels
an example scenario, not an archived forecast. Its weather stays fixed when the
user changes the trip date. There are no live weather, maps, traffic or park calls.

## Demo catalog

All values below are fictional. Distance is the complete loop; ascent is total
uphill gain, not summit altitude. Driving allowances are shown separately from
hiking, parking and breaks.

| Trail | Loop (miles) | Ascent (feet) | Demo dog rule | Drive out / back |
|---|---:|---:|---|---|
| Cedar Meadow Loop | 2 | 180 | Leashed dogs allowed | 20 min / 25 min |
| Amber Ridge Loop | 3 | 420 | Leashed dogs allowed | 35 min / 40 min |
| Willow Bank Walk | 4 | 120 | Leashed dogs allowed | 30 min / 35 min |
| Granite Crown Climb | 12 | 3,600 | Leashed dogs allowed | 1 hr 50 min / 2 hr  |
| Sunstone Hill Trail | 5 | 1,500 | Leashed dogs allowed | 1 hr 35 min / 1 hr 45 min |
| Cloudstep Peak Trail | 16 | 4,800 | No pet dogs | 1 hr 40 min / 1 hr 50 min |
| Fern Hollow Loop | 2.5 | 300 | No pet dogs | 55 min / 1 hr 5 min |
| Bluebird Canyon Loop | 4.5 | 900 | No pet dogs | 1 hr 20 min / 1 hr 30 min |
| Pine Arch Trail | 3.5 | 800 | Leashed dogs allowed | 1 hr  / 1 hr 10 min |
| Silver Crest Trail | 6 | 1,200 | Leashed dogs allowed | 1 hr 15 min / 1 hr 25 min |

All demo locations use opening hours of 6 AM to 8 PM daily. Dog rules are invented
planning constraints, not real park policies. Each dog's hiking capacity comes
from the user's trip details. No real alerts, permits or access status are represented.

## Viewing and changing the data

Run the app using [the setup guide](SETUP_START_AND_STOP.md). Enter a trip, open
**Results**, and choose **View hike** to inspect a matching trail. Open the JSON
files directly to see all ten records. **Start a new trip** clears old conversation
state after a dataset change.

When editing the catalog, keep the same destination identifiers in both JSON
files. The current loaders expect ten destinations. Changing metrics can change
which hikes match a request; old examples are not promises of identical results.

## Content and licenses

No downloaded trail photos, maps, website descriptions, reviews, third-party
route datasets or weather snapshots are included in these data files. No external
source attribution is claimed for the invented values.

Python dependencies and the local Ollama model are installed separately and
retain their own licenses. No model weights are bundled. No project-wide software
license has been selected; fictional data does not remove the need to respect
third-party software and model terms.
