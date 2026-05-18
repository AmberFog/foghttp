# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "foghttp",
# ]
#
# [tool.uv.sources]
# foghttp = { path = "../", editable = true }
# ///

import json

import foghttp
from foghttp.methods import POST


BASE_URL = "https://httpbin.org"


def print_httpbin_response(label: str, response: foghttp.Response) -> None:
    data = response.json()
    print(label, "status:", response.status_code)
    print(label, "request:", response.request.method, response.request.url)
    print(label, "args:", json.dumps(data.get("args", {}), sort_keys=True))
    print(label, "trace:", data["headers"].get("X-Trace"))


def main() -> None:
    with foghttp.Client(
        base_url=BASE_URL,
        headers={"accept": "application/json", "x-client": "foghttp-example"},
        params={"client": "foghttp", "api-version": "1"},
    ) as client:
        response = client.get(
            "anything/search?debug=1",
            params=[
                ("tag", "rust"),
                ("tag", "python"),
                ("limit", "2"),
            ],
            headers={"x-trace": "shortcut-request"},
        )
        response.raise_for_status()
        print_httpbin_response("shortcut", response)

        form_response = client.post(
            "anything/oauth/token",
            data={
                "grant_type": "client_credentials",
                "scope": ["read", "write"],
            },
            headers={"x-trace": "form-request"},
        )
        form_response.raise_for_status()
        print_httpbin_response("form", form_response)
        print("form data:", json.dumps(form_response.json().get("form"), sort_keys=True))

        request = client.build_request(
            POST,
            "anything/users",
            params={"source": "prepared"},
            json={"name": "Ada Lovelace", "role": "engineer"},
        )
        request.headers["x-trace"] = "prepared-request"

        prepared_response = client.send(request)
        prepared_response.raise_for_status()
        print_httpbin_response("prepared", prepared_response)
        print("prepared json:", json.dumps(prepared_response.json().get("json"), sort_keys=True))

        try:
            client.build_request(
                POST,
                "anything/body-conflict",
                data={"name": "Grace Hopper"},
                json={"name": "Grace Hopper"},
            )
        except ValueError as exc:
            print("body conflict:", exc)


if __name__ == "__main__":
    main()
