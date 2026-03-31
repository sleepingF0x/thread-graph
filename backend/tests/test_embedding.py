# backend/tests/test_embedding.py
import pytest
from unittest.mock import MagicMock, patch


def test_embedding_client_calls_openai():
    from app.embedding import EmbeddingClient

    mock_response = MagicMock()
    mock_response.data = [MagicMock(embedding=[0.1, 0.2, 0.3])]

    mock_openai = MagicMock()
    mock_openai.embeddings.create.return_value = mock_response

    with patch("app.embedding.OpenAI", return_value=mock_openai):
        client = EmbeddingClient(
            base_url="https://api.example.com/v1",
            api_key="test-key",
            model="test-model",
        )
        result = client.embed_sync(["hello"])

    assert result == [[0.1, 0.2, 0.3]]
    mock_openai.embeddings.create.assert_called_once_with(
        input=["hello"], model="test-model"
    )


def test_embedding_client_batches():
    from app.embedding import EmbeddingClient

    calls = []

    def fake_create(input, model):
        calls.append(len(input))
        return MagicMock(data=[MagicMock(embedding=[float(i)]) for i in range(len(input))])

    mock_openai = MagicMock()
    mock_openai.embeddings.create.side_effect = fake_create

    with patch("app.embedding.OpenAI", return_value=mock_openai):
        client = EmbeddingClient("url", "key", "model", batch_size=2)
        texts = ["a", "b", "c", "d", "e"]
        result = client.embed_sync(texts)

    assert len(result) == 5
    assert calls == [2, 2, 1]
