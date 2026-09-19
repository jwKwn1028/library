# Music records

Read this before adding an album or song. An album record describes one
release group (the album as a work across its editions), not one pressing. A
song record describes one recording of a song; see Songs below.

## Sources

Prefer, in order:

1. The MusicBrainz release group and its official releases. `lookup-media
   music` reads both.
2. The label's or artist's official release page.
3. Wikidata for cross-checking dates and identifiers.
4. Discogs or a streaming service only as a verified fallback.

Confirm the title, artist credit, primary type, first release date, and label.
MusicBrainz release groups can mix editions: use the first release date of the
release group and the label of its earliest dated official release, and say so
in the report if they conflict with another authoritative source.

## Album fields

| Field | Value |
| --- | --- |
| `entry_type` | `audio` |
| `title` | Release-group title exactly as released; never translate it |
| `author` | Credited artists. A person is `Family, Given`; wrap a group, orchestra, mononym, or `Various Artists` in braces, such as `{Example Ensemble}` |
| `date` | First release date, `YYYY-MM-DD` when known |
| `publisher` | Original label |
| `type` | `Album`, `EP`, or `Single`; APA renders it as `[Album]` |
| `musicbrainz` | Release-group ID (not a release or recording ID) |
| `wikidata` | Optional album item |
| `url` | Catalog `[URL]` target; prefer a stable album page on a streaming or official site |

Use `subtitle` for a genuine subtitle, not for edition notes such as
`Remastered` or `Deluxe Edition`. Do not store a label catalog number in
`number`: alongside `series`, the catalog renders `number` as a series position.

## Songs

Add a song as its own record only when the user asks for the song rather than
its album. `lookup-media` drafts albums only, so research a song directly:

1. Search MusicBrainz recordings by title and artist. When the user names an
   album or performance (such as a live album), choose the recording on that
   album's standard edition; a live take and its studio version are different
   recordings.
2. Take the release date and label from that album's primary official release,
   and confirm them and the track length with a second source such as the
   album's Wikipedia article or the label.
3. Link a track-level listening page. Confirm its title, artist, release year,
   and duration match the recording; a service can list several editions of
   the same track.

| Field | Value |
| --- | --- |
| `entry_type` | `audio` |
| `title` | Song title as released, without service suffixes such as `- Live at …` |
| `booktitle` | The album the recording appears on; Typst's APA style omits it |
| `author` | Credited artists, formatted as for albums |
| `date` | That album's release date |
| `publisher` | That album's label |
| `type` | `Song`; APA renders it as `[Song]` |
| `musicbrainz` | Recording ID (not the release group) |
| `url` | Track-level listening page |

## Keys and classification

Use `familyYYYYshorttitle` from the first credited artist: the family name for
a person; for a group, the first word of its MusicBrainz sort name (a group
named for a person, such as `Metheny, Pat, Group`, uses that family name),
otherwise its first significant word. For example,
`{Example Ensemble}` releasing `Synthetic Sessions` in 2026 becomes
`example2026syntheticsessions`. Append `a`, `b`, and so on only after a
collision.

Classify under `Music/<Genre>` by the album's primary tradition. Prefer
existing subtopics and create a narrower one only when it will recur. A
soundtrack belongs under `Music`, not `Film`; give it a subtitle such as
`Original Motion Picture Soundtrack` when the release uses one.

## Synthetic manifest

```json
{
  "topic": {
    "path": "Music/Jazz",
    "headings": ["Music", "Jazz"]
  },
  "items": [
    {
      "pending": true,
      "citation_key": "example2026syntheticsessions",
      "entry_type": "audio",
      "title": "Synthetic Sessions",
      "metadata_sources": [
        "https://musicbrainz.org/release-group/00000000-0000-4000-8000-000000000001"
      ],
      "fields": {
        "author": "{Example Ensemble}",
        "date": "2026-01-15",
        "publisher": "Example Records",
        "type": "Album",
        "musicbrainz": "00000000-0000-4000-8000-000000000001",
        "url": "https://music.example.org/album/synthetic-sessions"
      }
    }
  ]
}
```
