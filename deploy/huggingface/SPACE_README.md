---
title: Wardrobe Studio
emoji: 👗
colorFrom: purple
colorTo: pink
sdk: docker
app_port: 8080
pinned: false
license: mit
short_description: Design garments for VRM avatars and export wardrobes
---

# Wardrobe Studio · 3D Wardrobe Forge

A garment editor for VRM avatars, and the API behind it.

Open the Space and you are in the **Studio**: the five CC0 avatars that
[yourfriend.online](https://github.com/ruslanmv/yourfriend) ships, a 3D viewport,
and a designer whose every control comes from what the outfit planner actually
understands. Generate a look, compare it side by side with the original under the
same light, read its fit report, and export the wardrobe as a bundle that
[3D-Avatar-Chatbot](https://github.com/ruslanmv/3D-Avatar-Chatbot) and
yourfriend.online import by unzipping it.

| Path                                | What it is                                     |
| ----------------------------------- | ---------------------------------------------- |
| `/`                                 | redirects to the Studio                        |
| `/studio/`                          | the editor                                     |
| `/docs`                             | the API, interactive                           |
| `/v1/library`                       | the avatar library, with provenance and sha256 |
| `/v1/wardrobes/{avatar}/bundle.zip` | the export the chatbot imports                 |

The avatars are fetched at build time and verified against the SHA-256 pins in
`assets/library/models.json`; the build fails rather than serve other bytes.

Generation runs on the native engine: fast, dependency-free, and unable to hide
the body under a garment — so garments that layer over what she is wearing fit
best. The Studio says so beside every fit report.
