# Film records

Read this before adding a film. A record describes the film as a work, not a
particular disc, cut, or streaming listing.

## Sources

Prefer, in order:

1. The film's Wikidata item. `lookup-media film` reads its titles, directors,
   release dates, production companies, runtime, and IMDb ID.
2. A national film archive or catalog, such as the Korean Movie Database for
   Korean films, the AFI Catalog, or the BFI collections.
3. The distributor's or studio's official page.
4. IMDb or another secondary index only as a verified fallback.

Confirm the title, directors, first public release date, production company,
and whether the item is a feature, short, documentary, or television film.

## Title language

Use the title the user asks for. Otherwise use the English title for a foreign
film, as `lookup-media` does by default, and mention the original and Korean
titles it prints in the report. Pass `--language ko` for a Korean release title
or `--language original` for the original-language title. Check that the
catalog fonts cover the chosen script before selecting a title outside Latin or
Hangul.

## Fields

| Field | Value |
| --- | --- |
| `entry_type` | `movie` |
| `title` | Chosen title; keep a genuine subtitle in `subtitle` |
| `author` | Directors as `Family, Given`; braces when the family name is unknown |
| `date` | Earliest public release, often a festival premiere, `YYYY-MM-DD` when known |
| `publisher` | Production company or companies |
| `type` | `Film`; APA renders it as `[Film]` |
| `imdb` | Optional `tt…` title ID |
| `wikidata` | Optional film item |
| `url` | Catalog `[URL]` target; a legitimate full-length watch page when available, otherwise the IMDb or Wikidata page |

`lookup-media` offers a YouTube video as a watch link only when its duration
covers at least 90% of the film's runtime. Shorter videos are trailers, clips,
or partial uploads; it lists them but never selects one. A film distributed in
several parts has no single watch link, so use a reference page.

An EIDR film DOI may be stored in `doi`. Supply `url` explicitly as well:
without one, intake uses the DOI resolver page as the `[URL]` link.

## Keys and classification

Use `familyYYYYshorttitle` from the first director and the English title,
for example `director2026synthetichorizon` for `Synthetic Horizon`. Append
`a`, `b`, and so on only after a collision.

Classify under `Film/<Genre>` by the film's primary genre or movement. Prefer
existing subtopics; create a narrower one only when it will recur. An
adaptation belongs under `Film` even when its novel is cataloged under
`Literature`.

## Synthetic manifest

```json
{
  "topic": {
    "path": "Film/ScienceFiction",
    "headings": ["Film", "Science Fiction"]
  },
  "items": [
    {
      "pending": true,
      "citation_key": "director2026synthetichorizon",
      "entry_type": "movie",
      "title": "Synthetic Horizon",
      "metadata_sources": ["https://www.wikidata.org/wiki/Q4115189"],
      "fields": {
        "author": "Director, Dana",
        "date": "2026-03-01",
        "publisher": "Example Pictures",
        "type": "Film",
        "imdb": "tt0000000",
        "wikidata": "Q4115189",
        "url": "https://watch.example.org/title/synthetic-horizon"
      }
    }
  ]
}
```
