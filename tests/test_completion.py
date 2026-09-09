"""Streaming transport regressions; all requests use an in-memory transport."""
from __future__ import annotations

import asyncio
import json
import unittest
from unittest.mock import patch

import httpx

from services.llm import LLMError, LLMService
from services.translator import Translator, TranslationError
from services.chat import ChatSession


def event(content=None, **choice_fields):
    delta = {} if content is None else {'content': content}
    return 'data: ' + json.dumps({'choices': [{'delta': delta, **choice_fields}]}, ensure_ascii=False) + '\n\n'


class FragmentedStream(httpx.AsyncByteStream):
    def __init__(self, body):
        self.body = body.encode('utf-8')
        self.closed = False

    async def __aiter__(self):
        for i in range(0, len(self.body), 3):
            yield self.body[i:i + 3]

    async def aclose(self):
        self.closed = True


class CompletionTests(unittest.TestCase):
    def service(self, handler, cls=LLMService, host='https://example.test/v1'):
        return cls(base_url=host, api_key='test-key', model='deepseek-v4-flash',
                   client_factory=lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs))

    def test_fragmented_unicode_sse_ignores_reasoning_and_keepalives(self):
        reasoning = 'data: ' + json.dumps({'choices': [{'delta': {'reasoning_content': 'private reasoning'}}]}) + '\n\n'
        stream = FragmentedStream(': keepalive\n\n' + reasoning + event('你') + event('好') + event(finish_reason='stop') + 'data: {"choices":[]}\n\ndata: [DONE]\n\n')
        def handler(request):
            self.assertTrue(json.loads(request.content)['stream'])
            return httpx.Response(200, headers={'content-type': 'text/event-stream'}, stream=stream)
        chunks = []
        with self.assertLogs('services.completion', level='INFO') as logs:
            result = asyncio.run(self.service(handler).ask('secret selection', on_delta=chunks.append))
        self.assertEqual(result, '你好')
        self.assertEqual(chunks, ['你', '好'])
        self.assertTrue(stream.closed)
        log = '\n'.join(logs.output)
        self.assertIn('first_reasoning_s=', log)
        self.assertIn('first_text_s=', log)
        self.assertIn('total_s=', log)
        self.assertNotIn('secret selection', log)
        self.assertNotIn('test-key', log)
        self.assertNotIn('private reasoning', log)

    def test_receives_partial_text_before_response_finishes(self):
        async def scenario():
            release = asyncio.Event()
            received = asyncio.Event()
            class SlowStream(httpx.AsyncByteStream):
                async def __aiter__(self):
                    yield event('first').encode()
                    await release.wait()
                    yield (event(' second') + event(finish_reason='stop')).encode()
            service = self.service(lambda request: httpx.Response(200, headers={'content-type': 'text/event-stream'}, stream=SlowStream()))
            chunks = []
            def on_delta(text):
                chunks.append(text)
                received.set()
            task = asyncio.create_task(service.ask('hello', on_delta=on_delta))
            try:
                await asyncio.wait_for(received.wait(), 1)
                self.assertFalse(task.done())
                self.assertEqual(chunks, ['first'])
                release.set()
                self.assertEqual(await task, 'first second')
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        asyncio.run(scenario())

    def test_thinking_option_only_sent_to_official_deepseek(self):
        for host, expected in [('https://api.deepseek.com/v1', True), ('https://example.test/v1', False), ('https://api.deepseek.com.example.test/v1', False)]:
            with self.subTest(host=host):
                payloads = []
                def handler(request):
                    payloads.append(json.loads(request.content))
                    return httpx.Response(200, json={'choices': [{'message': {'content': 'ok'}}]})
                with patch.dict('os.environ', {'DEEPSEEK_THINKING': 'disabled'}):
                    asyncio.run(self.service(handler, host=host).ask('hello'))
                self.assertEqual('thinking' in payloads[0], expected)
                if expected:
                    self.assertEqual(payloads[0]['thinking'], {'type': 'disabled'})

    def test_translation_thinking_can_be_enabled(self):
        payloads = []
        def handler(request):
            payloads.append(json.loads(request.content))
            return httpx.Response(200, json={'choices': [{'message': {'content': 'water'}}]})
        with patch.dict('os.environ', {'DEEPSEEK_TRANSLATION_THINKING': 'enabled'}):
            service = self.service(handler, Translator, 'https://api.deepseek.com/v1')
        asyncio.run(service.translate('water'))
        self.assertEqual(payloads[0]['thinking'], {'type': 'enabled'})

    def test_json_response_and_explicit_nonstream_mode(self):
        for setting in ('true', 'false'):
            chunks = []
            def handler(request):
                self.assertEqual(json.loads(request.content)['stream'], setting == 'true')
                return httpx.Response(200, json={'choices': [{'message': {'content': 'reply'}}]})
            with patch.dict('os.environ', {'LLM_STREAM': setting}):
                service = self.service(handler)
            self.assertEqual(asyncio.run(service.ask('question', on_delta=chunks.append)), 'reply')
            self.assertEqual(chunks, ['reply'])

    def test_incomplete_or_invalid_stream_is_not_a_success(self):
        bodies = [event('partial'), event('partial') + event(finish_reason='length'), 'data: broken\n\n', 'data: {"error":{"message":"secret"}}\n\n', 'data: [DONE]\n\n']
        for body in bodies:
            with self.subTest(body=body):
                service = self.service(lambda request: httpx.Response(200, headers={'content-type': 'text/event-stream'}, stream=FragmentedStream(body)))
                with self.assertRaises(LLMError):
                    asyncio.run(service.ask('question', on_delta=lambda text: None))

    def test_failed_translation_is_not_cached(self):
        calls = []
        def handler(request):
            calls.append(request)
            return httpx.Response(200, headers={'content-type': 'text/event-stream'}, stream=FragmentedStream(event('partial')))
        service = self.service(handler, Translator)
        for _ in range(2):
            with self.assertRaises(TranslationError):
                asyncio.run(service.translate('water', on_delta=lambda text: None))
        self.assertEqual(len(calls), 2)
        self.assertFalse(service._cache)

    def test_translation_cache_separates_language_and_is_bounded(self):
        calls = []
        def handler(request):
            calls.append(request)
            return httpx.Response(200, json={'choices': [{'message': {'content': 'translated'}}]})
        service = self.service(handler, Translator)
        async def scenario():
            await service.translate('water')
            chunks = []
            await service.translate('water', on_delta=chunks.append)
            self.assertEqual(chunks, ['translated'])
            self.assertEqual(len(calls), 1)
            await service.translate('water', 'French')
            self.assertEqual(len(calls), 2)
            for i in range(128):
                await service.translate(str(i))
            self.assertEqual(len(service._cache), 128)
            await service.translate('water')
            self.assertEqual(len(calls), 131)
        asyncio.run(scenario())

    def test_cancellation_closes_stream_and_rolls_back_chat(self):
        async def scenario():
            received = asyncio.Event()
            class SlowStream(httpx.AsyncByteStream):
                closed = False
                async def __aiter__(self):
                    yield event('partial').encode()
                    await asyncio.sleep(60)
                async def aclose(self):
                    self.closed = True
            stream = SlowStream()
            service = self.service(lambda request: httpx.Response(200, headers={'content-type': 'text/event-stream'}, stream=stream))
            session = ChatSession('context', service)
            task = asyncio.create_task(session.send('question', on_delta=lambda text: received.set()))
            try:
                await asyncio.wait_for(received.wait(), 1)
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
            self.assertTrue(stream.closed)
            self.assertEqual(len(session.messages), 1)
        asyncio.run(scenario())
