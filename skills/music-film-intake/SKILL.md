---
name: music-film-intake
description: Add music albums, songs, and films to this library's Typst catalog as verified pending records whose catalog entry links to a web page until a local file path exists. Use for requests to add, catalog, recommend, or look up albums, songs, EPs, soundtracks, films, movies, or documentaries in this workspace, including MusicBrainz or Wikidata lookups and drafting intake manifests; do not use for papers or books (use paper-library-intake) or for unsolicited reorganization of existing records.
---

# Music and Film Intake

Albums and films use the paper library's transactional engine,
`scripts/intake-papers`; this skill supplies the judgment around it. A music or
film record is an ordinary BibLaTeX record that stays pending: its `file` field
is empty until a local copy exists, and its `url` field becomes a bracketed
`[URL]` link beside the catalog title. The title still links to its entry in
References.

## Record model

- Album: `entry_type: "audio"` with `fields.type` set to `Album` (or `EP`,
  `Single`). Put the credited artist in `author` and the record label in
  `publisher`.
- Song: `entry_type: "audio"` with `fields.type` set to `Song`, the album it
  appears on in `booktitle`, and that album's date and label.
- Film: `entry_type: "movie"` with `fields.type` set to `Film`. Put the
  director(s) in `author`; Typst omits an `editor`-only director for films.
  Put the production company in `publisher`.
- `date` is the earliest release. Prefer a full `YYYY-MM-DD`: Typst's APA
  style prints a year-only audiovisual date as `(1972,)`.
- `url` is the page the `[URL]` link opens: a listening or watching page when
  one is available, otherwise a stable reference page. It must be an HTTP(S) URL
  without credentials. Remove tracking query parameters such as `si` or
  `utm_*`.
- Optional identifiers `musicbrainz` (an album's release-group ID or a song's
  recording ID), `imdb` (`tt…`), and `wikidata` (`Q…`) accept bare IDs or page
  URLs. Intake stores bare IDs and rejects any identifier already in the
  library.
- Duplicate detection combines the normalized title with the medium, release
  year, and first creator, so a film can share a novel's title and a remake can
  coexist with the original.

Read [references/music.md](references/music.md) before adding an album or song
and [references/film.md](references/film.md) before adding a film. They define
field conventions, source priority, and synthetic manifest examples.

## Workflow

1. Work from the library root. Run `./scripts/init-library` if root `main.typ`
   or `library.bib` is missing.
2. Inspect the taxonomy with `./scripts/intake-papers topics --json`. Unless
   the user names other topics, use the top-level `Music` and `Film` topics and
   subdivide them by genre, tradition, or movement (for example `Music/Jazz` or
   `Film/ScienceFiction`), following the naming rules in `AGENTS.md`. Never
   file an album or film under `AdjacentFields`, the catch-all for adjacent
   research.
3. Find the work with the read-only lookup helper:

   ```sh
   ./scripts/lookup-media music "Album Title" --artist "Artist Name"
   ./scripts/lookup-media film "Film Title" --year 2026 --director "Name"
   ```

   Confirm the candidate is the intended work, not a compilation, reissue,
   remake, or television adaptation. `lookup-media` drafts albums, not songs;
   for a song, follow the song steps in the music reference.
4. Draft the record from its identifier:

   ```sh
   ./scripts/lookup-media music --id MUSICBRAINZ-RELEASE-GROUP-ID
   ./scripts/lookup-media film --id WIKIDATA-QID --language en
   ```

   `--language ko` or `--language original` selects another film title.
   `--link reference` prefers a reference page over a streaming page. Treat the
   draft as untrusted evidence: verify every field against its source, act on
   each printed note, and complete missing fields from authoritative sources.
5. Keep the drafted `url`, pick another printed link, or use the page the user
   provides.
6. Put the reviewed items in one manifest per topic, outside the repository.
   Each item has `pending: true` and omits `source_file` and
   `canonical_filename`.
7. Dry-run with `./scripts/intake-papers --manifest /tmp/music.json`. Check the
   `FILE  PENDING LOCAL PATH`, `LINK  [URL]`, `ID`, `KEY`, and `TITLE` lines,
   then repeat with `--apply`. The apply validates the library and rebuilds
   `Catalog.pdf` transactionally.
8. Report each citation key, topic, title, catalog URL, metadata source, and
   any `Library/` directory the apply created.

## Guardrails

- `lookup-media` is networked but writes nothing. `intake-papers` stays
  offline, and only it changes `library.bib`, `main.typ`, or `Catalog.pdf`.
- MusicBrainz and Wikidata ask clients to identify a contact. Set
  `PAPER_LIBRARY_LOOKUP_CONTACT` (an email address or URL) only in the runtime
  environment; never store or print it.
- Never invent a local path or placeholder media file. Local audio and video
  attachment is not supported yet, so these records remain pending with their
  `[URL]` link.
- Never put credentials, signed links, or private query data in `url` or
  `metadata_sources`.
- Do not use `scripts/fetch-pending`; it handles PDFs only and ignores albums
  and films.
- Keep manifests and reports private and Git-ignored; do not copy real records
  into `templates/`, `examples/`, or other public files.
- If the dry run or apply fails, fix the manifest and rerun it. Do not weaken
  a check or describe a rolled-back intake as complete.
