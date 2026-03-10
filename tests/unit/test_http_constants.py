"""Unit tests for HTTP constants."""
import pytest

from src.http.constants import HOP_BY_HOP_HEADERS


class TestHopByHopHeaders:
    """Test HOP_BY_HOP_HEADERS constant."""

    def test_is_frozenset(self):
        """HOP_BY_HOP_HEADERS should be immutable."""
        assert isinstance(HOP_BY_HOP_HEADERS, frozenset)

    def test_contains_all_rfc_2616_headers(self):
        """Should contain all RFC 2616 hop-by-hop headers."""
        required_headers = {
            "connection",
            "keep-alive",
            "proxy-authenticate",
            "proxy-authorization",
            "te",
            "trailer",
            "transfer-encoding",
            "upgrade",
        }
        assert required_headers == HOP_BY_HOP_HEADERS

    def test_immutability(self):
        """Should not allow modifications."""
        with pytest.raises(AttributeError):
            HOP_BY_HOP_HEADERS.add("new-header")  # type: ignore

        with pytest.raises(AttributeError):
            HOP_BY_HOP_HEADERS.remove("connection")  # type: ignore

    def test_membership_check_case_sensitive(self):
        """Membership checks should be case-sensitive."""
        assert "connection" in HOP_BY_HOP_HEADERS
        assert "Connection" not in HOP_BY_HOP_HEADERS
        assert "CONNECTION" not in HOP_BY_HOP_HEADERS

    def test_can_be_used_in_set_operations(self):
        """Should support set operations."""
        test_headers = {"connection", "content-type", "x-custom"}
        
        # Intersection
        hop_headers = test_headers & HOP_BY_HOP_HEADERS
        assert hop_headers == {"connection"}
        
        # Difference
        safe_headers = test_headers - HOP_BY_HOP_HEADERS
        assert safe_headers == {"content-type", "x-custom"}

    def test_filtering_headers_dict(self):
        """Should work for filtering headers dictionary."""
        headers = {
            "content-type": "application/json",
            "connection": "keep-alive",
            "transfer-encoding": "chunked",
            "x-request-id": "123",
        }
        
        filtered = {
            k: v for k, v in headers.items()
            if k.lower() not in HOP_BY_HOP_HEADERS
        }
        
        assert "content-type" in filtered
        assert "x-request-id" in filtered
        assert "connection" not in filtered
        assert "transfer-encoding" not in filtered

    def test_empty_intersection_with_safe_headers(self):
        """Safe headers should have no intersection."""
        safe_headers = {
            "content-type",
            "content-length",
            "authorization",
            "x-custom-header",
        }
        assert len(safe_headers & HOP_BY_HOP_HEADERS) == 0
