# Legal notices / Avvertenze legali

*English first — italiano più sotto.*

## English

### No warranty
Upmix51 is free software released under the [MIT licence](LICENSE). It is provided **"as is", without warranty of any kind**. The authors are not liable for any damage or data loss resulting from its use.

Upmix51 can write, replace and move files. Before using it on a media library:
- keep a **backup** of your files;
- mount your library **read-only** (`:ro`) unless you really need in-place overwriting;
- leave the "keep original audio track" and "backup" options enabled.

### Trademarks
Dolby, Dolby Digital and the double-D symbol are trademarks of Dolby Laboratories. Upmix51 is an independent project and is **not affiliated with, endorsed or certified by Dolby Laboratories**. The program produces audio in the AC-3 format (commonly known as Dolby Digital) using the open-source encoder included in FFmpeg; the AC-3 patents have expired.

iTunes and Apple are trademarks of Apple Inc. Deezer is a trademark of Deezer SA. MusicBrainz and Cover Art Archive are projects of the MetaBrainz Foundation. TMDB is a trademark of The Movie Database. Upmix51 is not affiliated with, endorsed or certified by any of them. All trademarks belong to their respective owners.

### Cover art and media
- Upmix51 **does not contain or redistribute** cover art, images or media. When the user asks for it, it queries public services and downloads the selected image **for the user's own files**.
- Cover art, posters and video frames are protected by the **copyright of their respective owners** (artists, labels, studios, photographers). Using them is the user's responsibility: use them only for your **personal collection** and do not redistribute them.
- This repository must not contain copyrighted covers, frames, audio or video. Screenshots in the documentation must use material you own or that is freely licensed.
- Use Upmix51 only on media you are legally entitled to process (for example your own discs, where the law of your country allows private copies).

### Online services used for cover search
Requests go directly from your Upmix51 instance to these services; please respect their terms:

| Service | Terms |
|---|---|
| iTunes Search API (Apple) | https://performance-partners.apple.com/search-api |
| Deezer API | https://developers.deezer.com/termsofuse |
| MusicBrainz API / Cover Art Archive | https://musicbrainz.org/doc/MusicBrainz_API · https://coverartarchive.org |
| TMDB API (optional, needs your own key) | https://www.themoviedb.org/api-terms-of-use |

MusicBrainz asks every application to identify itself: set `UA_CONTACT` to your project URL or e-mail (see the README).
When the optional TMDB key is used: *This product uses the TMDB API but is not endorsed or certified by TMDB.*

### Third-party software
See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). In particular, the Docker image you build contains a **GPL-licensed** build of FFmpeg: if you **redistribute a built image** (e.g. on Docker Hub) you must comply with the GPL.

This document is general information and not legal advice.

---

## Italiano

### Nessuna garanzia
Upmix51 è software libero rilasciato con [licenza MIT](LICENSE). È fornito **"così com'è", senza alcuna garanzia**. Gli autori non sono responsabili di danni o perdite di dati derivanti dal suo uso.

Upmix51 può scrivere, sostituire e spostare file. Prima di usarlo su una libreria multimediale:
- tieni una **copia di backup** dei tuoi file;
- monta la libreria in **sola lettura** (`:ro`), a meno che tu non abbia davvero bisogno della sovrascrittura;
- lascia attive le opzioni "conserva la traccia audio originale" e "backup".

### Marchi
Dolby, Dolby Digital e il simbolo della doppia D sono marchi di Dolby Laboratories. Upmix51 è un progetto indipendente e **non è affiliato, approvato o certificato da Dolby Laboratories**. Il programma produce audio nel formato AC-3 (noto come Dolby Digital) con l'encoder open source incluso in FFmpeg; i brevetti AC-3 sono scaduti.

iTunes e Apple sono marchi di Apple Inc. Deezer è un marchio di Deezer SA. MusicBrainz e Cover Art Archive sono progetti della MetaBrainz Foundation. TMDB è un marchio di The Movie Database. Upmix51 non è affiliato, approvato o certificato da nessuno di essi. Tutti i marchi appartengono ai rispettivi titolari.

### Copertine e contenuti
- Upmix51 **non contiene e non ridistribuisce** copertine, immagini o contenuti. Su richiesta dell'utente interroga servizi pubblici e scarica l'immagine scelta **per i file dell'utente**.
- Copertine, locandine e fotogrammi sono protetti dal **diritto d'autore dei rispettivi titolari** (artisti, etichette, studi, fotografi). L'uso è responsabilità dell'utente: usali solo per la tua **collezione personale** e non ridistribuirli.
- Questo repository non deve contenere copertine, fotogrammi, audio o video protetti. Gli screenshot della documentazione devono usare materiale tuo o con licenza libera.
- Usa Upmix51 solo su contenuti che hai il diritto di elaborare (per esempio i tuoi dischi, dove la legge del tuo paese consente la copia privata).

### Servizi online usati per le copertine
Le richieste partono direttamente dalla tua installazione verso i servizi elencati nella tabella in inglese: rispettane i termini d'uso. MusicBrainz chiede che ogni applicazione si identifichi: imposta `UA_CONTACT` con l'URL del progetto o un'e-mail.

### Software di terze parti
Vedi [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). In particolare, l'immagine Docker che costruisci contiene una versione di FFmpeg con licenza **GPL**: se **ridistribuisci un'immagine già costruita** (per esempio su Docker Hub) devi rispettare la GPL.

Questo documento è un'informazione generale e non una consulenza legale.
