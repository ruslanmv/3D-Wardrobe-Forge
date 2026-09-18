# Wardrobe manifest specification

A wardrobe is application metadata. VRM itself does not need to contain a standardized outfit list.

```json
{
  "schemaVersion": 1,
  "avatar": {
    "id": "mira",
    "sourceHash": "..."
  },
  "looks": [
    {
      "id": "look_burgundy",
      "name": "Burgundy Evening",
      "type": "vrmVariant",
      "vrmUrl": "https://cdn.example/look.vrm",
      "previewUrl": "https://cdn.example/preview.webp"
    }
  ]
}
```
