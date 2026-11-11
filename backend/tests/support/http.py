import httpx2


def set_cookies(response: httpx2.Response) -> dict[str, dict[str, str]]:
    cookies: dict[str, dict[str, str]] = {}
    for header in response.headers.get_list("set-cookie"):
        pair, *attributes = (part.strip() for part in header.split(";"))
        name, value = pair.split("=", 1)
        parsed = {"value": value}
        for attribute in attributes:
            key, _, attribute_value = attribute.partition("=")
            parsed[key.lower()] = attribute_value
        cookies[name] = parsed
    return cookies
