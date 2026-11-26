import {createClient} from 'redis';
const url=process.env.REDIS_URL;if(!url)throw new Error('REDIS_URL is required');
const client=createClient({url});client.on('error',e=>console.error('redis_connection_error',e.message));
await client.connect();console.info('Graphytion render worker connected to Redis transport.');console.info('Render execution consumer is registered in Phase 09; no render is acknowledged or simulated in this foundation.');
const shutdown=async()=>{await client.quit();process.exit(0);};process.once('SIGINT',shutdown);process.once('SIGTERM',shutdown);
