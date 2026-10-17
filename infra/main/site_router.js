// CloudFront Function (viewer request) for the site: map a page URL to its pre-rendered file.
//   /                    -> /index.html
//   /hospitals/030006    -> /hospitals/030006/index.html
//   /hospitals/030006/   -> /hospitals/030006/index.html
//   /assets/app-1a2b.js  -> unchanged (has an extension)
// A page that wasn't pre-rendered (a search, a rare service) has no such file; S3 answers
// 403 and the distribution's custom error response serves the app shell instead, which
// renders it in the browser. web/scripts/serve-build.mjs applies the same rule locally.
function handler(event) {
  var request = event.request;
  var uri = request.uri;
  if (uri.endsWith("/")) {
    request.uri = uri + "index.html";
  } else if (uri.lastIndexOf(".") <= uri.lastIndexOf("/")) {
    request.uri = uri + "/index.html";
  }
  return request;
}
