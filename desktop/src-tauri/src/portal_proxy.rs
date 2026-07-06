use std::sync::OnceLock;

use axum::body::{to_bytes, Body};
use axum::extract::Request;
use axum::http::{
    header, HeaderMap, HeaderName, HeaderValue, Method,
};
use axum::response::{IntoResponse, Response};
use reqwest::Client;

const PORTAL_UPSTREAM: &str = "https://www.tanjiyunai.com";
const MAX_BODY_BYTES: usize = 16 * 1024 * 1024;

static PORTAL_CLIENT: OnceLock<Client> = OnceLock::new();

fn portal_client() -> &'static Client {
    PORTAL_CLIENT.get_or_init(|| {
        Client::builder()
            .redirect(reqwest::redirect::Policy::none())
            .build()
            .expect("portal proxy client")
    })
}

fn hop_by_hop_request_headers() -> &'static [&'static str] {
    &[
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
        "host",
    ]
}

fn hop_by_hop_response_headers() -> &'static [&'static str] {
    &[
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
    ]
}

fn filter_request_headers(headers: &HeaderMap) -> HeaderMap {
    let mut out = HeaderMap::new();
    for (name, value) in headers {
        let lower = name.as_str().to_ascii_lowercase();
        if hop_by_hop_request_headers()
            .iter()
            .any(|blocked| lower == *blocked)
        {
            continue;
        }
        out.insert(name.clone(), value.clone());
    }
    out
}

fn rewrite_set_cookie(raw: &str) -> String {
    let mut parts = raw.split(';');
    let Some(first) = parts.next() else {
        return raw.to_string();
    };
    let mut out = vec![first.trim().to_string()];
    for part in parts {
        let trimmed = part.trim();
        if trimmed.is_empty() {
            continue;
        }
        let lower = trimmed.to_ascii_lowercase();
        if lower == "secure" || lower.starts_with("domain=") {
            continue;
        }
        if lower.starts_with("samesite=none") {
            out.push("SameSite=Lax".to_string());
            continue;
        }
        out.push(trimmed.to_string());
    }
    out.join("; ")
}

fn rewrite_location(location: &str) -> String {
    for prefix in [
        "https://www.tanjiyunai.com",
        "http://www.tanjiyunai.com",
        "https://tanjiyunai.com",
        "http://tanjiyunai.com",
    ] {
        if let Some(rest) = location.strip_prefix(prefix) {
            return rest.to_string();
        }
    }
    location.to_string()
}

fn append_header(response: &mut Response, name: HeaderName, value: HeaderValue) {
    if name == header::SET_COOKIE {
        response.headers_mut().append(name, value);
        return;
    }
    response.headers_mut().insert(name, value);
}

pub async fn proxy_portal_request(request: Request) -> Response {
    let (parts, body) = request.into_parts();
    let path_and_query = parts
        .uri
        .path_and_query()
        .map(|value| value.as_str())
        .unwrap_or("/");
    let upstream_url = format!("{PORTAL_UPSTREAM}{path_and_query}");

    let body_bytes = match to_bytes(body, MAX_BODY_BYTES).await {
        Ok(bytes) => bytes,
        Err(err) => {
            log::warn!("portal proxy body read failed: {err}");
            return axum::http::StatusCode::BAD_GATEWAY.into_response();
        }
    };

    let mut builder = portal_client().request(parts.method.clone(), &upstream_url);
    builder = builder.headers(filter_request_headers(&parts.headers));
    if !body_bytes.is_empty()
        && (parts.method == Method::POST
            || parts.method == Method::PUT
            || parts.method == Method::PATCH)
    {
        builder = builder.body(body_bytes.to_vec());
    }

    let upstream = match builder.send().await {
        Ok(response) => response,
        Err(err) => {
            log::warn!("portal proxy upstream failed {upstream_url}: {err}");
            return axum::http::StatusCode::BAD_GATEWAY.into_response();
        }
    };

    let status = axum::http::StatusCode::from_u16(upstream.status().as_u16())
        .unwrap_or(axum::http::StatusCode::BAD_GATEWAY);
    let upstream_headers = upstream.headers().clone();
    let payload = match upstream.bytes().await {
        Ok(bytes) => bytes,
        Err(err) => {
            log::warn!("portal proxy response read failed: {err}");
            return axum::http::StatusCode::BAD_GATEWAY.into_response();
        }
    };

    let mut response = match Response::builder()
        .status(status)
        .body(Body::from(payload))
    {
        Ok(response) => response,
        Err(err) => {
            log::warn!("portal proxy response build failed: {err}");
            return axum::http::StatusCode::INTERNAL_SERVER_ERROR.into_response();
        }
    };

    for (name, value) in upstream_headers.iter() {
        let lower = name.as_str().to_ascii_lowercase();
        if hop_by_hop_response_headers()
            .iter()
            .any(|blocked| lower == *blocked)
        {
            continue;
        }
        if lower == "set-cookie" {
            let Ok(raw) = value.to_str() else { continue };
            let rewritten = rewrite_set_cookie(raw);
            if let Ok(parsed) = HeaderValue::from_str(&rewritten) {
                append_header(&mut response, header::SET_COOKIE, parsed);
            }
            continue;
        }
        if lower == "location" {
            if let Ok(raw) = value.to_str() {
                if let Ok(parsed) = HeaderValue::from_str(&rewrite_location(raw)) {
                    append_header(&mut response, header::LOCATION, parsed);
                }
            }
            continue;
        }
        append_header(&mut response, name.clone(), value.clone());
    }

    response
}
