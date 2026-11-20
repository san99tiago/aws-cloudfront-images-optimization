// Rufus Bank: image content negotiation at the edge (CloudFront Functions, runtime cloudfront-js-2.0).
//
// Public URL : /img/<campaign>/<imageId>/<version>?w=<css px>&dpr=<1..3>&q=<auto|standard|lite>&f=<auto|avif|webp|jpeg>
// Origin key : /<campaign>/<imageId>/<version>/<width>w-<quality>.<ext>
//
// Why: the cache policy keeps headers, cookies and query strings OUT of the cache key. This function turns the
// thousands of possible raw requests (any width, any DPR, any Accept header) into a handful of normalized
// variants and writes the decision into the URI, so every variant is cached exactly once per edge.
//
// Placeholders (__WIDTHS__, __DEFAULT_WIDTH__) are replaced by the CDK stack with the values from cdk.json.

var WIDTHS = __WIDTHS__;
var DEFAULT_WIDTH = __DEFAULT_WIDTH__;
var MAX_DPR = 3;
var MAX_CSS_WIDTH = 4096;
var EXTENSIONS = { avif: 'avif', webp: 'webp', jpeg: 'jpg' };
var PUBLIC_PATH = /^\/img\/([a-z0-9-]{1,64})\/([a-z0-9-]{1,64})\/([a-f0-9]{8,64})\/?$/;
var VARIANT_PATH = /^\/[a-z0-9-]{1,64}\/[a-z0-9-]{1,64}\/[a-f0-9]{8,64}\/(\d{2,4}w-(standard|lite)\.(avif|webp|jpg)|original\.(png|jpg|jpeg|webp))$/;

function queryValue(querystring, name) {
  var item = querystring[name];
  if (!item) {
    return '';
  }
  var value = item.multiValue && item.multiValue.length ? item.multiValue[0].value : item.value;
  return String(value || '').toLowerCase();
}

function headerValue(headers, name) {
  var item = headers[name];
  return item ? String(item.value || '').toLowerCase() : '';
}

// Smallest breakpoint that covers the requested physical width (never upscale above the largest variant)
function snapWidth(physicalWidth) {
  for (var i = 0; i < WIDTHS.length; i++) {
    if (WIDTHS[i] >= physicalWidth) {
      return WIDTHS[i];
    }
  }
  return WIDTHS[WIDTHS.length - 1];
}

function pickWidth(querystring, headers) {
  var cssWidth = parseInt(queryValue(querystring, 'w'), 10);
  var dpr = parseFloat(queryValue(querystring, 'dpr') || headerValue(headers, 'sec-ch-dpr') || headerValue(headers, 'dpr') || '1');
  if (!(dpr >= 1)) {
    dpr = 1;
  }
  if (dpr > MAX_DPR) {
    dpr = MAX_DPR;
  }
  if (!(cssWidth > 0)) {
    // Client hint Sec-CH-Width already comes in physical pixels
    var hinted = parseInt(headerValue(headers, 'sec-ch-width'), 10);
    return snapWidth(hinted > 0 ? hinted : DEFAULT_WIDTH);
  }
  return snapWidth(Math.ceil(Math.min(cssWidth, MAX_CSS_WIDTH) * dpr));
}

// Explicit format wins; otherwise the best format the client accepts (AVIF > WebP > JPEG)
function pickFormat(requested, accept) {
  if (requested === 'avif' || requested === 'webp' || requested === 'jpeg') {
    return requested;
  }
  if (requested === 'jpg') {
    return 'jpeg';
  }
  if (accept.indexOf('image/avif') !== -1) {
    return 'avif';
  }
  if (accept.indexOf('image/webp') !== -1) {
    return 'webp';
  }
  return 'jpeg';
}

// Explicit tier wins; "auto" honors the data saver and slow networks (Save-Data and ECT client hints)
function pickQuality(requested, headers) {
  if (requested === 'standard' || requested === 'lite') {
    return requested;
  }
  if (headerValue(headers, 'save-data') === 'on') {
    return 'lite';
  }
  var ect = headerValue(headers, 'ect');
  if (ect === 'slow-2g' || ect === '2g' || ect === '3g') {
    return 'lite';
  }
  return 'standard';
}

function handler(event) {
  var request = event.request;
  var uri = request.uri;

  // Direct variant URLs (debugging and the optimization lab) map to the same cache key
  if (VARIANT_PATH.test(uri)) {
    request.querystring = {};
    return request;
  }

  var match = uri.match(PUBLIC_PATH);
  if (!match) {
    // Strict allow-list of paths: nothing else ever reaches the bucket
    return {
      statusCode: 404,
      statusDescription: 'Not Found',
      headers: { 'cache-control': { value: 'public, max-age=300' } },
    };
  }

  var querystring = request.querystring;
  var headers = request.headers;
  var width = pickWidth(querystring, headers);
  var format = pickFormat(queryValue(querystring, 'f'), headerValue(headers, 'accept'));
  var quality = pickQuality(queryValue(querystring, 'q'), headers);

  request.uri = '/' + match[1] + '/' + match[2] + '/' + match[3] + '/' + width + 'w-' + quality + '.' + EXTENSIONS[format];
  // The origin never needs the query string: the decision already lives in the URI (the cache key)
  request.querystring = {};
  return request;
}
