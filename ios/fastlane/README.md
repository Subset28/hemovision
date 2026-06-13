fastlane documentation
----

# Installation

Make sure you have the latest version of the Xcode command line tools installed:

```sh
xcode-select --install
```

For _fastlane_ installation instructions, see [Installing _fastlane_](https://docs.fastlane.tools/#installing-fastlane)

# Available Actions

## iOS

### ios build

```sh
[bundle exec] fastlane ios build
```

Build release IPA

### ios push_metadata

```sh
[bundle exec] fastlane ios push_metadata
```

Push metadata to App Store Connect without uploading binary

### ios upload

```sh
[bundle exec] fastlane ios upload
```

Upload pre-built IPA to TestFlight

### ios beta

```sh
[bundle exec] fastlane ios beta
```

Build + upload to TestFlight

### ios release

```sh
[bundle exec] fastlane ios release
```

Build + submit to App Store review

### ios bump_build

```sh
[bundle exec] fastlane ios bump_build
```

Bump build number using ASC latest + 1

----

This README.md is auto-generated and will be re-generated every time [_fastlane_](https://fastlane.tools) is run.

More information about _fastlane_ can be found on [fastlane.tools](https://fastlane.tools).

The documentation of _fastlane_ can be found on [docs.fastlane.tools](https://docs.fastlane.tools).
