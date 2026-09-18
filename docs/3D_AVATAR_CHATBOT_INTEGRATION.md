# 3D-Avatar-Chatbot integration

```js
const job = await forge.createLook({
  avatarUrl: currentAvatarUrl,
  prompt: 'elegant burgundy evening dress'
});

const ready = await forge.wait(job.id);
await wardrobe.applyLook(ready.look);

// Later:
await wardrobe.restore();
```

Temporary outfit changes should not be driven through the persistent avatar picker.
