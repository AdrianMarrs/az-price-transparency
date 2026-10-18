// CloudFront Function (viewer request) for the site: map a page URL to its pre-rendered file.
//   /                    -> /index.html
//   /hospitals/030006    -> /hospitals/030006/index.html
//   /hospitals/030006/   -> /hospitals/030006/index.html
//   /assets/app-1a2b.js  -> unchanged (has an extension)
// A page that wasn't pre-rendered (a search, a rare service) has no such file; S3 answers
// 403 and the distribution's custom error response serves the app shell instead, which
// renders it in the browser. web/scripts/serve-build.mjs applies the same rule locally.
//
// Once the site's own domain is live (domain.tf), any other name it's reached by (www, the
// CloudFront name) gets a permanent redirect to it. Terraform fills in APEX; empty until then.
var APEX = "${apex}";

function handler(event) {
  var request = event.request;
  var uri = request.uri;
  var host = request.headers.host ? request.headers.host.value : "";
  if (APEX && host !== APEX) {
    return {
      statusCode: 301,
      statusDescription: "Moved Permanently",
      headers: { location: { value: "https://" + APEX + uri + query(request.querystring) } },
    };
  }
  if (uri.endsWith("/")) {
    request.uri = uri + "index.html";
  } else if (uri.lastIndexOf(".") <= uri.lastIndexOf("/")) {
    request.uri = uri + "/index.html";
  }
  return request;
}

// CloudFront hands over the query string parsed ({name: {value, multiValue}}), still
// percent-encoded; this puts it back together.
function query(qs) {
  var parts = [];
  Object.keys(qs).forEach(function (name) {
    var values = qs[name].multiValue ? qs[name].multiValue : [qs[name]];
    values.forEach(function (v) {
      parts.push(v.value === "" ? name : name + "=" + v.value);
    });
  });
  return parts.length ? "?" + parts.join("&") : "";
}
