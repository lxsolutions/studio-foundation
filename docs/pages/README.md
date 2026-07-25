# GitHub Pages source

`index.html` is the canonical source for the repository's Pages landing page.

The live site currently uses GitHub's legacy branch deployment:

- branch: `gh-pages`
- path: `/`
- generated Pages workflow: `dynamic/pages/pages-build-deployment`
- live URL: <https://lxsolutions.github.io/studio-foundation/>

The exported Godot applications and `chariot.png` remain on `gh-pages`.
`.github/workflows/pages.yml` copies only this canonical `index.html` onto that
branch after a trusted push to `main`, preserving `demo/`, `showcase/`, their
wasm/pck files, and the image.

Validate the source and required public links with:

```sh
just public-evidence-validate
```

Do not hand-edit the deployed `gh-pages/index.html` without applying the same
change here. The next successful source sync will replace it.
