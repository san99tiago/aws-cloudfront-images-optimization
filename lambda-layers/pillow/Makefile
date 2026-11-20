# Pillow (with AVIF and WebP) for AWS Lambda Python 3.14 on arm64 (Graviton).
# Pillow 13 wheels bundle libavif and libwebp, so no Docker build is needed: pip downloads the Linux wheel.
PYTHON ?= python3
PYTHON_VERSION ?= 3.14

install:
	[ -d "modules/python" ] || $(PYTHON) -m pip install -r requirements.txt -t modules/python/ \
		--platform manylinux_2_28_aarch64 --platform manylinux2014_aarch64 \
		--implementation cp --python-version $(PYTHON_VERSION) \
		--only-binary=:all: --upgrade --quiet --disable-pip-version-check

clean:
	rm -rf modules/python
