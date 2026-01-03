#!/bin/bash

# Word Chain Game Docker Helper Script

case "$1" in
    build)
        echo "Building Docker image..."
        docker-compose build
        ;;
    up)
        echo "Starting Word Chain Bot..."
        docker-compose up -d
        ;;
    down)
        echo "Stopping Word Chain Bot..."
        docker-compose down
        ;;
    logs)
        echo "Showing bot logs..."
        docker-compose logs -f word-chain-bot
        ;;
    restart)
        echo "Restarting Word Chain Bot..."
        docker-compose restart word-chain-bot
        ;;
    shell)
        echo "Opening shell in container..."
        docker-compose exec word-chain-bot /bin/bash
        ;;
    clean)
        echo "Cleaning up Docker resources..."
        docker-compose down -v
        docker system prune -f
        ;;
    *)
        echo "Word Chain Game Docker Helper"
        echo ""
        echo "Usage: $0 {build|up|down|logs|restart|shell|clean}"
        echo ""
        echo "Commands:"
        echo "  build   - Build the Docker image"
        echo "  up      - Start the bot in background"
        echo "  down    - Stop the bot"
        echo "  logs    - Show bot logs"
        echo "  restart - Restart the bot"
        echo "  shell   - Open shell in container"
        echo "  clean   - Remove containers and volumes"
        echo ""
        exit 1
        ;;
esac