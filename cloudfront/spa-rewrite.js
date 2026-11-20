// Rufus Bank portal: SPA routing at the edge (CloudFront Functions, runtime cloudfront-js-2.0).
//
// Real files (with an extension, for example /assets/index-3f9a1c.js or /config.json) are served as they are.
// Application routes (for example /dashboard) are rewritten to /index.html so React Router can handle them.
// This keeps real 403/404 errors intact, unlike distribution-wide custom error responses that would also hide
// errors from the /api/* behavior.

function handler(event) {
  var request = event.request;
  var uri = request.uri;
  var lastSegment = uri.substring(uri.lastIndexOf('/') + 1);

  if (lastSegment.indexOf('.') === -1) {
    request.uri = '/index.html';
  }
  return request;
}
