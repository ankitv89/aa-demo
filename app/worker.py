import asyncio
from confluent_kafka import Consumer, Producer

async def consume_notifications():
    consumer = Consumer({
        'bootstrap.servers': 'localhost:9092',
        'group.id': 'notification-worker',
        'auto.offset.reset': 'earliest'
    })
    consumer.subscribe(['notifications.send'])

    while True:
        msg = consumer.poll(1.0)
        if msg is None:
            continue
        if msg.error():
            print(f"Consumer error: {msg.error()}")
            continue

        print(f"Received message: {msg.value().decode('utf-8')}")
        # Process the message and send notification

    consumer.close()

if __name__ == "__main__":
    asyncio.run(consume_notifications())
