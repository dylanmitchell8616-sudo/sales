"""DNS and email deliverability setup helper.

Generates, verifies, and optionally auto-adds DNS records (SPF, DKIM, DMARC,
MX, custom tracking domain CNAME) needed for cold email deliverability.
Supports auto-configuration via the Cloudflare API.

Usage:
    >>> dns = DNSSetup("yourdomain.com")
    >>> dns.print_checklist()
    >>> dns.verify_all()
    >>> dns.add_via_cloudflare(zone_id="...", api_token="...")
"""

from __future__ import annotations

import os
from typing import Any

try:
    import dns.resolver
    _HAS_DNSPYTHON = True
except ImportError:
    _HAS_DNSPYTHON = False

try:
    import requests
    _HAS_REQUESTS = True
except ImportError:
    _HAS_REQUESTS = False


class DNSSetup:
    """Generate, verify, and optionally auto-add DNS records for email deliverability.

    Supports SPF, DKIM, DMARC, MX, and custom tracking-domain CNAME records.

    Args:
        domain: The sending domain (e.g. ``"acme.co"``).
        tracking_subdomain: Subdomain used for Instantly open/click tracking.
            Defaults to ``"track"``.
        dkim_selector: DKIM selector string.  Defaults to ``"default"``.
    """

    # Instantly's tracking CNAME target
    INSTANTLY_TRACKING_CNAME = "tracking.instantly.ai"

    def __init__(
        self,
        domain: str,
        tracking_subdomain: str = "track",
        dkim_selector: str = "default",
    ) -> None:
        self.domain = domain.lower().strip()
        self.tracking_subdomain = tracking_subdomain.lower().strip()
        self.dkim_selector = dkim_selector

    # ------------------------------------------------------------------
    # Record generation
    # ------------------------------------------------------------------

    def generate_spf_record(
        self,
        includes: list[str] | None = None,
        policy: str = "~all",
    ) -> dict[str, str]:
        """Generate an SPF TXT record.

        Args:
            includes: Extra SPF include domains (e.g. ``["zoho.com"]``).
                Common providers are added by default.
            policy: SPF policy suffix.  ``"~all"`` (soft fail) is recommended
                for deliverability during ramp-up; switch to ``"-all"`` later.

        Returns:
            A DNS record dict with ``type``, ``name``, ``value``.
        """
        parts = ["v=spf1"]
        for inc in (includes or []):
            parts.append(f"include:{inc}")
        parts.append(policy)
        return {
            "type": "TXT",
            "name": self.domain,
            "value": " ".join(parts),
            "purpose": "SPF - Authorizes mail servers to send on your behalf",
        }

    def generate_dkim_record(
        self,
        public_key: str = "<PASTE_YOUR_DKIM_PUBLIC_KEY_HERE>",
        selector: str | None = None,
    ) -> dict[str, str]:
        """Generate a DKIM TXT record.

        The actual public key must be obtained from your email provider's
        admin panel and pasted into the ``public_key`` argument.

        Args:
            public_key: The base64-encoded RSA public key.
            selector:   Override the default selector.

        Returns:
            DNS record dict.
        """
        sel = selector or self.dkim_selector
        return {
            "type": "TXT",
            "name": f"{sel}._domainkey.{self.domain}",
            "value": f"v=DKIM1; k=rsa; p={public_key}",
            "purpose": "DKIM - Email signing verification",
        }

    def generate_dmarc_record(
        self,
        policy: str = "none",
        rua_email: str | None = None,
        ruf_email: str | None = None,
        subdomain_policy: str = "none",
        aspf: str = "r",
    ) -> dict[str, str]:
        """Generate a DMARC TXT record.

        Args:
            policy: ``"none"``, ``"quarantine"``, or ``"reject"``.
                Start with ``"none"`` to monitor before enforcing.
            rua_email: Email address for aggregate reports.
            ruf_email: Email address for forensic reports.
            subdomain_policy: Policy for subdomains.
            aspf: SPF alignment (``"r"`` = relaxed, ``"s"`` = strict).

        Returns:
            DNS record dict.
        """
        rua = rua_email or f"dmarc-reports@{self.domain}"
        ruf = ruf_email or f"dmarc-reports@{self.domain}"
        value = (
            f"v=DMARC1; p={policy}; "
            f"rua=mailto:{rua}; ruf=mailto:{ruf}; "
            f"sp={subdomain_policy}; aspf={aspf};"
        )
        return {
            "type": "TXT",
            "name": f"_dmarc.{self.domain}",
            "value": value,
            "purpose": "DMARC - Email authentication policy",
        }

    def generate_tracking_cname(self, target: str | None = None) -> dict[str, str]:
        """Generate a CNAME record for a custom tracking domain.

        Instantly (and most cold email platforms) use a tracking domain for
        open/click tracking.  A custom subdomain avoids shared-domain
        reputation issues.

        Args:
            target: The CNAME target.  Defaults to Instantly's tracking host.

        Returns:
            DNS record dict.
        """
        return {
            "type": "CNAME",
            "name": f"{self.tracking_subdomain}.{self.domain}",
            "value": target or self.INSTANTLY_TRACKING_CNAME,
            "purpose": "Custom tracking domain for Instantly (improves deliverability)",
        }

    def generate_mx_records(
        self,
        provider: str = "zoho",
    ) -> list[dict[str, str]]:
        """Generate MX records for common free email providers.

        Args:
            provider: ``"zoho"``, ``"outlook"``, ``"gmail"``, or ``"custom"``.

        Returns:
            List of MX record dicts.
        """
        mx_configs: dict[str, list[dict[str, Any]]] = {
            "zoho": [
                {"priority": "10", "value": "mx.zoho.com", "purpose": "Primary mail server"},
                {"priority": "20", "value": "mx2.zoho.com", "purpose": "Secondary mail server"},
                {"priority": "50", "value": "mx3.zoho.com", "purpose": "Tertiary mail server"},
            ],
            "outlook": [
                {
                    "priority": "10",
                    "value": f"{self.domain.replace('.', '-')}.mail.protection.outlook.com",
                    "purpose": "Outlook mail server",
                },
            ],
            "gmail": [
                {"priority": "1", "value": "aspmx.l.google.com", "purpose": "Primary Google MX"},
                {"priority": "5", "value": "alt1.aspmx.l.google.com", "purpose": "Alt Google MX"},
                {"priority": "5", "value": "alt2.aspmx.l.google.com", "purpose": "Alt Google MX"},
                {"priority": "10", "value": "alt3.aspmx.l.google.com", "purpose": "Alt Google MX"},
                {"priority": "10", "value": "alt4.aspmx.l.google.com", "purpose": "Alt Google MX"},
            ],
            "custom": [
                {"priority": "10", "value": f"mail.{self.domain}", "purpose": "Custom mail server"},
            ],
        }
        entries = mx_configs.get(provider.lower(), mx_configs["zoho"])
        return [
            {
                "type": "MX",
                "name": self.domain,
                "value": e["value"],
                "priority": e["priority"],
                "purpose": e.get("purpose", "Mail exchange"),
            }
            for e in entries
        ]

    def generate_all_records(
        self,
        provider: str = "zoho",
        spf_includes: list[str] | None = None,
        dkim_public_key: str = "<PASTE_YOUR_DKIM_PUBLIC_KEY_HERE>",
    ) -> list[dict[str, str]]:
        """Generate a complete set of DNS records for email sending.

        Includes MX, SPF, DKIM, DMARC, and tracking CNAME.

        Args:
            provider:        Mail provider for MX records.
            spf_includes:    Additional SPF include domains.
            dkim_public_key: Your DKIM public key.

        Returns:
            Ordered list of all DNS record dicts.
        """
        includes = list(spf_includes or [])
        # Auto-add the provider's SPF include if not already present
        provider_spf_map = {
            "zoho": "zoho.com",
            "outlook": "spf.protection.outlook.com",
            "gmail": "_spf.google.com",
        }
        prov_include = provider_spf_map.get(provider.lower())
        if prov_include and prov_include not in includes:
            includes.insert(0, prov_include)

        # Provider-specific DKIM selectors
        provider_dkim_selectors = {
            "zoho": "zmail",
            "gmail": "google",
            "outlook": "selector1",
        }
        dkim_sel = provider_dkim_selectors.get(provider.lower(), self.dkim_selector)

        records: list[dict[str, str]] = []
        records.extend(self.generate_mx_records(provider))
        records.append(self.generate_spf_record(includes=includes))
        records.append(self.generate_dkim_record(public_key=dkim_public_key, selector=dkim_sel))
        records.append(self.generate_dmarc_record())
        records.append(self.generate_tracking_cname())
        return records

    # ------------------------------------------------------------------
    # Verification via dnspython
    # ------------------------------------------------------------------

    def verify_spf(self) -> dict[str, Any]:
        """Check whether a valid SPF record exists for the domain.

        Returns:
            Dict with ``found`` (bool), ``records`` (list of values), and
            ``valid`` (bool -- True if a ``v=spf1`` record exists).
        """
        return self._verify_txt(self.domain, prefix="v=spf1")

    def verify_dkim(self, selector: str | None = None) -> dict[str, Any]:
        """Check whether a DKIM record exists.

        Args:
            selector: Override the default DKIM selector.

        Returns:
            Verification result dict.
        """
        sel = selector or self.dkim_selector
        name = f"{sel}._domainkey.{self.domain}"
        return self._verify_txt(name, prefix="v=DKIM1")

    def verify_dmarc(self) -> dict[str, Any]:
        """Check whether a DMARC record exists.

        Returns:
            Verification result dict.
        """
        return self._verify_txt(f"_dmarc.{self.domain}", prefix="v=DMARC1")

    def verify_mx(self) -> dict[str, Any]:
        """Check whether MX records exist for the domain.

        Returns:
            Dict with ``found`` (bool) and ``records`` (list of MX hosts).
        """
        self._require_dnspython()
        try:
            answers = dns.resolver.resolve(self.domain, "MX")
            records = [
                {"priority": r.preference, "host": str(r.exchange).rstrip(".")}
                for r in answers
            ]
            return {"found": True, "records": records}
        except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN, dns.resolver.NoNameservers):
            return {"found": False, "records": []}
        except Exception as exc:
            return {"found": False, "records": [], "error": str(exc)}

    def verify_tracking_cname(self) -> dict[str, Any]:
        """Check whether the tracking CNAME record exists.

        Returns:
            Verification result dict.
        """
        self._require_dnspython()
        fqdn = f"{self.tracking_subdomain}.{self.domain}"
        try:
            answers = dns.resolver.resolve(fqdn, "CNAME")
            values = [str(r.target).rstrip(".") for r in answers]
            return {
                "found": True,
                "records": values,
                "valid": any(
                    self.INSTANTLY_TRACKING_CNAME in v for v in values
                ),
            }
        except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN, dns.resolver.NoNameservers):
            return {"found": False, "records": [], "valid": False}
        except Exception as exc:
            return {"found": False, "records": [], "valid": False, "error": str(exc)}

    def verify_all(self) -> dict[str, Any]:
        """Run all DNS verification checks and return a summary.

        Returns:
            Dict keyed by record type with each verification result, plus
            an ``all_valid`` boolean.
        """
        results = {
            "domain": self.domain,
            "mx": self.verify_mx(),
            "spf": self.verify_spf(),
            "dkim": self.verify_dkim(),
            "dmarc": self.verify_dmarc(),
            "tracking_cname": self.verify_tracking_cname(),
        }
        results["all_valid"] = all(
            r.get("found", False)
            for k, r in results.items()
            if isinstance(r, dict) and k != "domain"
        )
        return results

    # ------------------------------------------------------------------
    # Human-readable checklist
    # ------------------------------------------------------------------

    def print_checklist(
        self,
        provider: str = "zoho",
        spf_includes: list[str] | None = None,
        dkim_public_key: str = "<PASTE_YOUR_DKIM_PUBLIC_KEY_HERE>",
    ) -> str:
        """Print a formatted checklist of all DNS records to add.

        Args:
            provider:        Mail provider for MX records.
            spf_includes:    Extra SPF includes.
            dkim_public_key: Your DKIM public key.

        Returns:
            The formatted checklist string.
        """
        records = self.generate_all_records(
            provider=provider,
            spf_includes=spf_includes,
            dkim_public_key=dkim_public_key,
        )

        lines: list[str] = [
            f"\n{'='*64}",
            f"  DNS Setup Checklist for {self.domain}",
            f"{'='*64}\n",
            "Add these records in your domain registrar's DNS settings:\n",
        ]

        for i, rec in enumerate(records, 1):
            priority = rec.get("priority", "")
            purpose = rec.get("purpose", "")
            lines.append(f"  [ ] {i}. {rec['type']} Record")
            lines.append(f"       Name:     {rec['name']}")
            lines.append(f"       Value:    {rec['value']}")
            if priority:
                lines.append(f"       Priority: {priority}")
            if purpose:
                lines.append(f"       Why:      {purpose}")
            lines.append("")

        lines.append("After adding records, allow 15-60 min for propagation,")
        lines.append("then run  dns.verify_all()  to confirm everything is live.")
        lines.append("")
        lines.append("NOTE: DNS changes can take up to 48 hours to fully propagate.")

        output = "\n".join(lines)
        print(output)
        return output

    # ------------------------------------------------------------------
    # Cloudflare auto-add
    # ------------------------------------------------------------------

    def add_via_cloudflare(
        self,
        zone_id: str | None = None,
        api_token: str | None = None,
        provider: str = "zoho",
        spf_includes: list[str] | None = None,
        dkim_public_key: str = "<PASTE_YOUR_DKIM_PUBLIC_KEY_HERE>",
        proxied: bool = False,
    ) -> list[dict[str, Any]]:
        """Automatically add all DNS records via the Cloudflare API.

        Requires a Cloudflare API token with ``Zone.DNS`` edit permissions.

        Args:
            zone_id:         Cloudflare zone ID for the domain.  If ``None``,
                             auto-detected from the API.
            api_token:       Cloudflare API token.  Falls back to
                             ``CLOUDFLARE_API_TOKEN`` env var.
            provider:        Mail provider for MX records.
            spf_includes:    Extra SPF includes.
            dkim_public_key: DKIM public key.
            proxied:         Whether to proxy records through Cloudflare
                             (should be ``False`` for mail records).

        Returns:
            List of Cloudflare API response dicts, one per record.
        """
        if not _HAS_REQUESTS:
            raise RuntimeError("The 'requests' library is required for Cloudflare API calls.")

        token = api_token or os.getenv("CLOUDFLARE_API_TOKEN")
        if not token:
            raise ValueError(
                "Cloudflare API token required. Pass api_token= or set "
                "CLOUDFLARE_API_TOKEN environment variable."
            )

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }

        # Auto-detect zone ID if not provided
        if not zone_id:
            zone_id = self._cf_get_zone_id(token)
            if not zone_id:
                raise ValueError(
                    f"Domain {self.domain} not found in Cloudflare account. "
                    "Provide zone_id explicitly."
                )

        records = self.generate_all_records(
            provider=provider,
            spf_includes=spf_includes,
            dkim_public_key=dkim_public_key,
        )

        cf_url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records"
        results: list[dict[str, Any]] = []

        for rec in records:
            # Skip DKIM placeholder records
            if "<PASTE_YOUR_DKIM_PUBLIC_KEY_HERE>" in rec.get("value", ""):
                results.append({
                    "record": f"{rec['type']} {rec['name']}",
                    "status": "skipped",
                    "reason": "DKIM key placeholder -- paste real key first",
                })
                print(f"  [SKIP] {rec['type']:5s} {rec['name']} (DKIM placeholder)")
                continue

            payload: dict[str, Any] = {
                "type": rec["type"],
                "name": rec["name"],
                "content": rec["value"],
                "ttl": 1,  # auto
                "proxied": proxied if rec["type"] in ("A", "AAAA", "CNAME") else False,
            }
            if rec["type"] == "MX":
                payload["priority"] = int(rec.get("priority", 10))

            try:
                resp = requests.post(cf_url, headers=headers, json=payload, timeout=30)
                data = resp.json()
                status = "added" if data.get("success") else "error"
                print(f"  [{'OK' if status == 'added' else 'FAIL'}] {rec['type']:5s} {rec['name']}")
                if not data.get("success"):
                    for err in data.get("errors", []):
                        print(f"        Error: {err.get('message', err)}")
                results.append({
                    "record": f"{rec['type']} {rec['name']}",
                    "status": status,
                    "detail": data.get("errors", []) if status == "error" else data.get("result", {}),
                })
            except Exception as exc:
                print(f"  [FAIL] {rec['type']:5s} {rec['name']}: {exc}")
                results.append({
                    "record": f"{rec['type']} {rec['name']}",
                    "status": "error",
                    "detail": str(exc),
                })

        return results

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _cf_get_zone_id(self, api_token: str) -> str | None:
        """Auto-detect the Cloudflare zone ID for ``self.domain``."""
        resp = requests.get(
            "https://api.cloudflare.com/client/v4/zones",
            headers={"Authorization": f"Bearer {api_token}"},
            params={"name": self.domain},
            timeout=30,
        )
        data = resp.json()
        zones = data.get("result", [])
        return zones[0]["id"] if zones else None

    @staticmethod
    def _require_dnspython() -> None:
        if not _HAS_DNSPYTHON:
            raise RuntimeError(
                "dnspython is required for DNS verification. "
                "Install it with:  pip install dnspython"
            )

    def _verify_txt(self, name: str, prefix: str) -> dict[str, Any]:
        """Look up TXT records and check for a value starting with *prefix*."""
        self._require_dnspython()
        try:
            answers = dns.resolver.resolve(name, "TXT")
            values = [
                b"".join(r.strings).decode("utf-8", errors="replace")
                for r in answers
            ]
            matching = [v for v in values if v.startswith(prefix)]
            return {
                "found": len(values) > 0,
                "records": values,
                "valid": len(matching) > 0,
            }
        except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN, dns.resolver.NoNameservers):
            return {"found": False, "records": [], "valid": False}
        except Exception as exc:
            return {"found": False, "records": [], "valid": False, "error": str(exc)}

    def __repr__(self) -> str:
        return f"<DNSSetup domain={self.domain!r}>"
